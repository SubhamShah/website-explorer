import asyncio
import posixpath
import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from . import store
from .accessibility import load_axe_source, run_accessibility_scan
from .health import calculate_health_score, health_summary_payload
from .quality import (
    DEFAULT_CONTENT_CHECKS,
    PLACEHOLDER_PATTERN,
    aggregate_quality_findings,
    discover_sitemap_urls,
    page_content_findings,
)
from .responsive import capture_responsive_evidence, responsive_findings
from .security import passive_security_findings
from .templates import attach_template_metadata, template_metadata

SCREENSHOTS = Path(__file__).resolve().parents[1] / "data" / "screenshots"
USER_AGENT = "BugBusterWebsiteExplorer/0.2"
NAVIGATION_TIMEOUT_MS = 30_000
DEFAULT_RATE_LIMIT_MS = 750
MAX_ROBOTS_DELAY_SECONDS = 10
DEFAULT_SCAN_OPTIONS = {
    "page_health": True,
    "performance": True,
    "seo": True,
    "content_quality": True,
    "screenshots": True,
    "responsive": False,
    "accessibility": False,
    "console": False,
    "network": False,
    "sitemap_indexing": False,
    "template_intelligence": False,
    "passive_security": False,
}
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "dclid", "msclkid"}
RETRYABLE_PAGE_STATUSES = {404, 408, 425, 429, 500, 502, 503, 504}
ANALYTICS_HOST_SUFFIXES = {
    "google-analytics.com",
    "googletagmanager.com",
    "googleadservices.com",
    "doubleclick.net",
    "google.com",
    "google.com.np",
    "cloudflareinsights.com",
    "analytics.ahrefs.com",
    "posthog.com",
}


@dataclass
class ScanControl:
    resume_event: asyncio.Event


_BACKGROUND_TASKS: dict[str, asyncio.Task] = {}
_SCAN_CONTROLS: dict[str, ScanControl] = {}


@dataclass
class RobotsPolicy:
    parser: RobotFileParser | None
    status: str
    detail: str
    rate_limit_ms: int = DEFAULT_RATE_LIMIT_MS
    disallow_all: bool = False

    def allows(self, url: str) -> bool:
        if self.disallow_all:
            return False
        return self.parser is None or self.parser.can_fetch(USER_AGENT, url)


def normalize_url(value: str) -> str:
    """Return a stable crawl key without changing meaningful page parameters."""
    if not isinstance(value, str):
        return ""
    parsed = urlparse(value.strip())
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not scheme or not hostname:
        return value.strip()

    try:
        hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError:
        pass
    port = parsed.port
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = hostname if not port or default_port else f"{hostname}:{port}"

    raw_path = parsed.path or "/"
    had_trailing_slash = raw_path.endswith("/")
    path = posixpath.normpath("/" + raw_path.lstrip("/"))
    if had_trailing_slash and path != "/":
        path += "/"
    path = quote(path, safe="/:@-._~!$&'()*+,;=%")
    if path != "/":
        path = path.rstrip("/")

    query_items = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_QUERY_KEYS
    ]
    query = urlencode(sorted(query_items), doseq=True)
    return urlunparse((scheme, netloc, path, "", query, ""))


def site_origin(value: str) -> str:
    parsed = urlparse(normalize_url(value))
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


def same_site(candidate: str, origin: str) -> bool:
    candidate_parsed = urlparse(normalize_url(candidate))
    origin_parsed = urlparse(normalize_url(origin))
    return (
        candidate_parsed.scheme in {"http", "https"}
        and candidate_parsed.scheme == origin_parsed.scheme
        and candidate_parsed.hostname == origin_parsed.hostname
        and candidate_parsed.port == origin_parsed.port
    )


def normalize_links(values: object, root_url: str) -> list[str]:
    if not isinstance(values, list):
        return []
    links: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        try:
            candidate = normalize_url(urljoin(root_url, value))
            if candidate and same_site(candidate, root_url):
                links.add(candidate)
        except (TypeError, ValueError):
            continue
    return sorted(links)


def should_retry_page_status(status: int) -> bool:
    return status in RETRYABLE_PAGE_STATUSES


def network_request_failed(item: dict) -> bool:
    status = item.get("status")
    return not isinstance(status, int) or status >= 400


def _host_matches(hostname: str, suffixes: set[str]) -> bool:
    return any(hostname == suffix or hostname.endswith(f".{suffix}") for suffix in suffixes)


def classify_network_item(page_url: str, item: dict) -> dict:
    enriched = dict(item)
    request_host = (urlparse(str(item.get("url", ""))).hostname or "").lower()
    page_host = (urlparse(page_url).hostname or "").lower()
    if request_host == page_host:
        classification = "first_party"
    elif request_host == "challenges.cloudflare.com":
        classification = "security_challenge"
    elif request_host == "embed.tawk.to" or request_host.endswith(".tawk.to"):
        classification = "live_chat"
    elif _host_matches(request_host, ANALYTICS_HOST_SUFFIXES):
        classification = "advertising_analytics"
    else:
        classification = "third_party_functional"

    failed = network_request_failed(item)
    error = str(item.get("error", ""))
    if not failed:
        failure_kind = "none"
    elif item.get("blocked_by_crawler"):
        failure_kind = "scanner_blocked"
    elif "ERR_BLOCKED_BY_CLIENT" in error:
        failure_kind = "client_blocked"
    elif "ERR_ABORTED" in error:
        failure_kind = "browser_aborted"
    elif isinstance(item.get("status"), int):
        failure_kind = "http_error"
    else:
        failure_kind = "network_error"

    if not failed or failure_kind in {"scanner_blocked", "client_blocked", "browser_aborted"}:
        severity = "info"
    elif classification == "advertising_analytics":
        severity = "info"
    elif classification == "first_party":
        severity = "high"
    else:
        severity = "medium"

    enriched.update(
        {
            "classification": classification,
            "failure_kind": failure_kind,
            "severity": severity,
            "first_party": classification == "first_party",
        }
    )
    return enriched


def network_request_actionable(item: dict) -> bool:
    return network_request_failed(item) and item.get("severity") in {"medium", "high", "critical"}


def network_finding(page_url: str, item: dict) -> dict:
    item = classify_network_item(page_url, item) if "classification" not in item else item
    resource_type = item.get("resource_type", "other")
    resource_label = "API" if resource_type in {"fetch", "xhr"} else resource_type.replace("_", " ").title()
    classification_labels = {
        "first_party": "First-party",
        "advertising_analytics": "Analytics",
        "security_challenge": "Security challenge",
        "live_chat": "Live chat",
        "third_party_functional": "Third-party",
    }
    label = classification_labels[item["classification"]]
    failed = network_request_failed(item)
    status = item.get("status", "failed")
    result_labels = {
        "scanner_blocked": "blocked by scanner",
        "client_blocked": "blocked by client",
        "browser_aborted": "aborted by browser",
    }
    result = result_labels.get(item["failure_kind"], "failed" if failed else "passed")
    detail = f"{item.get('method', 'GET')} {item.get('url')} returned {status}."
    if item.get("error"):
        detail = f"{detail} {item['error']}"
    detail = f"{detail} Classification: {item['classification'].replace('_', ' ')}."
    return {
        "page_url": page_url,
        "severity": item["severity"],
        "category": "network",
        "title": f"{label} {resource_label} request {result}",
        "detail": detail[:500],
    }


def _correlated_network_item(console_item: dict, network: list[dict]) -> dict | None:
    failed_items = [item for item in network if network_request_failed(item)]
    location = console_item.get("location")
    location_url = location.get("url") if isinstance(location, dict) else None
    if location_url:
        exact = [item for item in failed_items if item.get("url") == location_url]
        if exact:
            return exact[0]
    error_codes = re.findall(r"net::ERR_[A-Z_]+", str(console_item.get("message", "")))
    if error_codes:
        matching = [
            item
            for item in failed_items
            if any(code in str(item.get("error", "")) for code in error_codes)
        ]
        if len(matching) == 1:
            return matching[0]
    if "Failed to load resource" in str(console_item.get("message", "")) and len(failed_items) == 1:
        return failed_items[0]
    return None


def classify_console_item(page_url: str, item: dict, network: list[dict]) -> dict:
    enriched = dict(item)
    message = str(item.get("message", ""))
    level = str(item.get("level", "error"))
    if (
        "postMessage" in message
        and "challenges.cloudflare.com" in message
        and "origin ('null')" in message
    ):
        enriched.update(
            {
                "classification": "scanner_side_effect",
                "severity": "info",
                "failure_kind": "blocked_security_iframe",
                "related_request_url": "https://challenges.cloudflare.com",
            }
        )
        return enriched

    embedded_url = re.search(r"https?://[^\s'\"<>]+", message)
    if embedded_url and ("CORS policy" in message or "blocked by CORS" in message):
        request_url = embedded_url.group(0).rstrip(".,;:)")
        related = classify_network_item(
            page_url,
            {
                "method": "GET",
                "url": request_url,
                "status": "failed",
                "resource_type": "script",
                "error": "CORS policy blocked the request",
            },
        )
        enriched.update(
            {
                "classification": related.get("classification", "network"),
                "severity": related.get("severity", "medium"),
                "failure_kind": "cors_error",
                "related_request_url": request_url,
            }
        )
        return enriched

    related = _correlated_network_item(item, network)
    if related:
        enriched.update(
            {
                "classification": related.get("classification", "network"),
                "severity": related.get("severity", "medium"),
                "failure_kind": related.get("failure_kind", "network_error"),
                "related_request_url": related.get("url"),
            }
        )
        return enriched

    enriched.update(
        {
            "classification": "browser_console",
            "severity": "low" if level == "warning" else "medium",
            "failure_kind": "uncorrelated_console_message",
            "related_request_url": None,
        }
    )
    return enriched


def console_finding(page_url: str, item: dict) -> dict:
    classification = str(item.get("classification", "browser_console"))
    level = str(item.get("level", "error"))
    if classification == "scanner_side_effect":
        title = "Browser warning caused by blocked security challenge"
    elif item.get("related_request_url"):
        title = f"Browser {level} linked to {classification.replace('_', ' ')} request"
    else:
        title = f"Browser {level}"
    detail = str(item.get("message", ""))
    if item.get("related_request_url"):
        detail = f"{detail} Related request: {item['related_request_url']}."
    return {
        "page_url": page_url,
        "severity": item.get("severity", "medium"),
        "category": "console",
        "title": title,
        "detail": detail[:500],
        "related_request_url": item.get("related_request_url"),
    }


async def load_robots_policy(context: object, root_url: str) -> RobotsPolicy:
    robots_url = urljoin(f"{site_origin(root_url)}/", "robots.txt")
    try:
        response = await context.request.get(
            robots_url,
            headers={"User-Agent": USER_AGENT},
            timeout=10_000,
            fail_on_status_code=False,
        )
        status = response.status
        if status == 200:
            parser = RobotFileParser()
            parser.set_url(robots_url)
            parser.parse((await response.text()).splitlines())
            delay = parser.crawl_delay(USER_AGENT) or parser.crawl_delay("*") or 0
            delay = min(float(delay), MAX_ROBOTS_DELAY_SECONDS)
            return RobotsPolicy(
                parser=parser,
                status="respected",
                detail=f"Loaded {robots_url}.",
                rate_limit_ms=max(DEFAULT_RATE_LIMIT_MS, round(delay * 1000)),
            )
        if status in {401, 403}:
            return RobotsPolicy(None, "blocked", f"{robots_url} returned {status}; crawling is denied.", disallow_all=True)
        if 500 <= status <= 599:
            return RobotsPolicy(None, "unavailable", f"{robots_url} returned {status}; crawling stopped conservatively.", disallow_all=True)
        return RobotsPolicy(None, "not_published", f"{robots_url} returned {status}; no crawl rules were published.")
    except Exception as error:
        return RobotsPolicy(None, "unavailable", f"Could not read {robots_url}: {str(error)[:180]}", disallow_all=True)


async def scan_website(
    scan_id: str,
    root_url: str,
    max_pages: int,
    max_depth: int,
    content_checks: dict | None = None,
    scan_options: dict | None = None,
) -> None:
    control = _SCAN_CONTROLS.get(scan_id)
    store.update_scan(
        scan_id,
        status="running" if control is None or control.resume_event.is_set() else "paused",
    )
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    normalized_root = normalize_url(root_url)
    queue = deque([(normalized_root, 0)])
    queued = {normalized_root}
    visited: set[str] = set()
    page_count = console_count = failed_request_count = timeout_count = 0
    retried_page_count = recovered_page_count = 0
    network_request_count = api_request_count = passed_request_count = 0
    actionable_failed_request_count = ignored_failed_request_count = 0
    skipped_robots = blocked_redirects = 0
    responsive_viewport_count = 0
    options = {**DEFAULT_SCAN_OPTIONS, **(scan_options or {})}
    score_enabled = any(
        options[key]
        for key in (
            "page_health", "performance", "seo", "content_quality", "responsive",
            "accessibility", "console", "network", "sitemap_indexing",
            "passive_security",
        )
    )
    settings = {**DEFAULT_CONTENT_CHECKS, **(content_checks or {})}
    if not options["content_quality"]:
        settings = {
            key: (value if key == "short_content_words" else False)
            for key, value in settings.items()
        }
    settings["indexing"] = options["sitemap_indexing"]
    page_records: list[dict] = []
    site_analysis: dict = {}
    findings: list[dict] = []
    axe_source = None
    if options["accessibility"]:
        try:
            axe_source = load_axe_source()
        except RuntimeError as accessibility_error:
            findings.append(
                {
                    "page_url": normalized_root,
                    "severity": "low",
                    "category": "accessibility",
                    "title": "Accessibility engine unavailable",
                    "detail": str(accessibility_error),
                }
            )
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1440, "height": 900},
                ignore_https_errors=False,
            )
            policy = await load_robots_policy(context, normalized_root)
            sitemap = (
                await discover_sitemap_urls(context, normalized_root)
                if options["sitemap_indexing"]
                else {"sources": [], "urls": [], "errors": [], "truncated": False}
            )
            normalized_sitemap_urls = set()
            for sitemap_item in sitemap.get("urls", []):
                try:
                    normalized_sitemap_url = normalize_url(sitemap_item)
                except ValueError:
                    continue
                if normalized_sitemap_url and same_site(normalized_sitemap_url, normalized_root):
                    normalized_sitemap_urls.add(normalized_sitemap_url)
            sitemap["urls"] = sorted(normalized_sitemap_urls)
            for sitemap_url in sitemap["urls"][: max(0, max_pages - 1)]:
                if sitemap_url != normalized_root and sitemap_url not in queued:
                    queue.append((sitemap_url, 0))
                    queued.add(sitemap_url)
            if policy.disallow_all and options["page_health"]:
                findings.append(
                    {
                        "page_url": normalized_root,
                        "severity": "high",
                        "category": "crawler",
                        "title": "Crawl blocked by robots policy",
                        "detail": policy.detail,
                    }
                )

            last_navigation_started = 0.0
            while queue and page_count < max_pages and not policy.disallow_all:
                if control is not None:
                    # Pause only between pages so a partially loaded page is
                    # never discarded or repeated when the scan resumes.
                    await control.resume_event.wait()
                url, depth = queue.popleft()
                queued.discard(url)
                if url in visited or depth > max_depth:
                    continue
                visited.add(url)
                if not policy.allows(url):
                    skipped_robots += 1
                    if options["page_health"]:
                        findings.append(
                            {
                                "page_url": url,
                                "severity": "low",
                                "category": "crawler",
                                "title": "Page skipped by robots.txt",
                                "detail": "The published robots policy does not allow this crawler to visit the page.",
                            }
                        )
                    continue

                elapsed_ms = (perf_counter() - last_navigation_started) * 1000
                if last_navigation_started and elapsed_ms < policy.rate_limit_ms:
                    await asyncio.sleep((policy.rate_limit_ms - elapsed_ms) / 1000)

                console: list[dict] = []
                network: list[dict] = []
                redirects: list[dict] = []
                crawler_blocked_urls: set[str] = set()
                page = await context.new_page()
                if options["console"]:
                    page.on(
                        "console",
                        lambda message: console.append(
                            {
                                "level": message.type,
                                "message": message.text,
                                "location": message.location,
                            }
                        )
                        if message.type in {"error", "warning"}
                        else None,
                    )
                def capture_response(response: object) -> None:
                    if options["network"]:
                        network.append(
                            {
                                "method": response.request.method,
                                "url": response.url,
                                "status": response.status,
                                "resource_type": response.request.resource_type,
                            }
                        )
                    if 300 <= response.status < 400 and response.request.is_navigation_request():
                        redirects.append(
                            {
                                "from": response.url,
                                "status": response.status,
                                "to": urljoin(response.url, response.headers.get("location", "")),
                            }
                        )

                page.on("response", capture_response)
                def capture_failed_request(request: object) -> None:
                    network.append(
                        {
                            "method": request.method,
                            "url": request.url,
                            "status": "failed",
                            "resource_type": request.resource_type,
                            "error": request.failure or "The browser could not complete this request.",
                            "blocked_by_crawler": request.url in crawler_blocked_urls,
                        }
                    )

                if options["network"]:
                    page.on("requestfailed", capture_failed_request)

                async def enforce_navigation_boundary(route: object) -> None:
                    if route.request.is_navigation_request() and not same_site(route.request.url, normalized_root):
                        crawler_blocked_urls.add(route.request.url)
                        await route.abort("blockedbyclient")
                    else:
                        await route.continue_()

                await page.route("**/*", enforce_navigation_boundary)
                started = perf_counter()
                last_navigation_started = started
                load_ms = 0
                status, title, h1, meta_description, links = 0, "", "", "", []
                responsive = {}
                screenshot_path = None
                final_url = url
                error_type = error_detail = None
                response_headers: dict = {}
                security_evidence: dict = {}
                try:
                    response = await page.goto(url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
                    load_ms = round((perf_counter() - started) * 1000)
                    initial_status = response.status if response else 0
                    if should_retry_page_status(initial_status):
                        retried_page_count += 1
                        await page.wait_for_timeout(policy.rate_limit_ms)
                        retry_started = perf_counter()
                        retry_response = await page.goto(
                            url,
                            wait_until="domcontentloaded",
                            timeout=NAVIGATION_TIMEOUT_MS,
                        )
                        if retry_response:
                            response = retry_response
                        load_ms = round((perf_counter() - retry_started) * 1000)
                        if response and response.status < 400:
                            recovered_page_count += 1
                    final_url = normalize_url(page.url)
                    response_headers = response.headers if response else {}
                    if not same_site(final_url, normalized_root):
                        blocked_redirects += 1
                        error_type = "cross_domain_redirect"
                        error_detail = f"Navigation redirected outside the authorized domain to {final_url}."
                    else:
                        await page.wait_for_timeout(350)
                        status = response.status if response else 0
                        page_data = await page.evaluate(
                            """() => ({
                                title: document.title || '',
                                h1: document.querySelector('h1')?.textContent || '',
                                h1_count: document.querySelectorAll('h1').length,
                                meta_description: document.querySelector('meta[name="description"]')?.getAttribute('content') || '',
                                canonical_urls: [...document.querySelectorAll('link[rel~="canonical"]')]
                                    .map(node => node.href || node.getAttribute('href') || '').filter(Boolean),
                                robots_directives: [...document.querySelectorAll('meta[name="robots"],meta[name="googlebot"]')]
                                    .map(node => node.getAttribute('content') || ''),
                                visible_text: (document.querySelector('main') || document.body)?.innerText || '',
                                images_missing_alt: [...document.images]
                                    .filter(node => !node.hasAttribute('alt') || !node.getAttribute('alt')?.trim())
                                    .map(node => node.currentSrc || node.src || node.outerHTML.slice(0, 100)).slice(0, 20),
                                images_missing_alt_count: [...document.images]
                                    .filter(node => !node.hasAttribute('alt') || !node.getAttribute('alt')?.trim()).length,
                                links: [...document.querySelectorAll('a[href]')].map(node => {
                                    const href = node.getAttribute('href');
                                    if (typeof href !== 'string') return null;
                                    try { return new URL(href, document.baseURI).href; }
                                    catch { return null; }
                                }).filter(Boolean),
                                template_tokens: [...document.querySelectorAll(
                                    'header,nav,main,main>*,article,aside,footer,form'
                                )].slice(0, 100).map(node => {
                                    const classes = [...node.classList]
                                        .filter(value => value.length < 50)
                                        .slice(0, 4)
                                        .sort()
                                        .join('.');
                                    return `${node.tagName.toLowerCase()}${node.getAttribute('role') ? `[${node.getAttribute('role')}]` : ''}${classes ? `.${classes}` : ''}`;
                                }),
                                insecure_resources: [...document.querySelectorAll(
                                    'script[src],iframe[src],link[rel~="stylesheet"][href],img[src],audio[src],video[src],source[src]'
                                )].map(node => node.src || node.href || '').filter(value => value.startsWith('http://')).slice(0, 20),
                                active_insecure_resource_count: [...document.querySelectorAll('script[src],iframe[src],link[rel~="stylesheet"][href]')]
                                    .filter(node => (node.src || node.href || '').startsWith('http://')).length,
                                insecure_form_actions: [...document.forms].map(node => node.getAttribute('action') || '')
                                    .filter(value => value.trim().toLowerCase().startsWith('http://')).slice(0, 10),
                                password_input_count: document.querySelectorAll('input[type="password"]').length,
                            })"""
                        )
                        security_evidence = {
                            "insecure_resources": page_data.get("insecure_resources", []),
                            "active_insecure_resource_count": page_data.get("active_insecure_resource_count", 0),
                            "insecure_form_actions": page_data.get("insecure_form_actions", []),
                            "password_input_count": page_data.get("password_input_count", 0),
                        }
                        title = page_data["title"]
                        h1 = page_data["h1"]
                        meta_description = page_data["meta_description"]
                        links = normalize_links(page_data.get("links"), normalized_root)
                        visible_text = str(page_data.get("visible_text", ""))
                        canonical_urls = []
                        for canonical_value in page_data.get("canonical_urls", []):
                            try:
                                canonical_urls.append(
                                    normalize_url(canonical_value)
                                    if canonical_value.startswith(("http://", "https://"))
                                    else canonical_value
                                )
                            except ValueError:
                                canonical_urls.append(canonical_value)
                        quality = {
                            "h1_count": page_data.get("h1_count", 0),
                            "canonical_urls": canonical_urls,
                            "robots_directives": page_data.get("robots_directives", []),
                            "noindex": any(
                                "noindex" in directive.lower()
                                for directive in page_data.get("robots_directives", [])
                            ) or (
                                response is not None
                                and "noindex" in response.headers.get("x-robots-tag", "").lower()
                            ),
                            "word_count": len(re.findall(r"\b[\w'-]+\b", visible_text)),
                            "placeholder_matches": sorted(
                                {match.group(0).lower() for match in PLACEHOLDER_PATTERN.finditer(visible_text)}
                            ),
                            "images_missing_alt": page_data.get("images_missing_alt", []),
                            "images_missing_alt_count": page_data.get("images_missing_alt_count", 0),
                            "template": (
                                template_metadata(url, page_data.get("template_tokens", []))
                                if options["template_intelligence"]
                                else {}
                            ),
                        }
                        if options["responsive"]:
                            try:
                                responsive = await capture_responsive_evidence(
                                    page,
                                    SCREENSHOTS,
                                    f"{scan_id}-{page_count + 1}",
                                )
                                screenshot_path = responsive.get("desktop", {}).get("screenshot_path")
                                responsive_viewport_count += len(responsive)
                            except Exception as responsive_error:
                                findings.append(
                                    {
                                        "page_url": url,
                                        "severity": "low",
                                        "category": "responsive",
                                        "title": "Responsive capture incomplete",
                                        "detail": f"Viewport evidence could not be completed: {str(responsive_error)[:240]}",
                                    }
                                )
                        elif options["screenshots"]:
                            try:
                                screenshot_filename = f"{scan_id}-{page_count + 1}-desktop.png"
                                await page.set_viewport_size({"width": 1440, "height": 900})
                                await page.screenshot(
                                    path=str(SCREENSHOTS / screenshot_filename),
                                    full_page=True,
                                )
                                screenshot_path = screenshot_filename
                            except Exception:
                                screenshot_path = None
                        if status < 400 and axe_source:
                            try:
                                await page.set_viewport_size({"width": 1440, "height": 900})
                                await page.wait_for_timeout(100)
                                accessibility_results, accessibility_summary = await run_accessibility_scan(
                                    page,
                                    url,
                                    axe_source,
                                    screenshot_path,
                                    SCREENSHOTS,
                                    f"{scan_id}-{page_count + 1}",
                                )
                                if not options["template_intelligence"]:
                                    for accessibility_result in accessibility_results:
                                        accessibility_result.get("metadata", {}).pop("component_hint", None)
                                findings.extend(accessibility_results)
                                quality["accessibility"] = accessibility_summary
                            except Exception as accessibility_error:
                                findings.append(
                                    {
                                        "page_url": url,
                                        "severity": "low",
                                        "category": "accessibility",
                                        "title": "Accessibility scan incomplete",
                                        "detail": (
                                            "axe-core could not complete this page: "
                                            f"{str(accessibility_error)[:240]}"
                                        ),
                                    }
                                )
                except PlaywrightTimeoutError:
                    load_ms = round((perf_counter() - started) * 1000)
                    timeout_count += 1
                    error_type = "timeout"
                    error_detail = f"Navigation did not reach DOM content loaded within {NAVIGATION_TIMEOUT_MS:,} ms."
                    if options["network"]:
                        network.append({"method": "GET", "url": url, "status": "timeout", "resource_type": "document", "error": error_detail})
                except Exception as error:
                    load_ms = round((perf_counter() - started) * 1000)
                    error_type = "navigation_error"
                    error_detail = str(error)[:300]
                    if options["network"]:
                        network.append({"method": "GET", "url": url, "status": "failed", "resource_type": "document", "error": error_detail})

                page_count += 1
                await page.close()
                network = [classify_network_item(url, item) for item in network]
                console = [classify_console_item(url, item, network) for item in console]
                store.save_page(
                    scan_id,
                    {
                        "url": url,
                        "final_url": final_url,
                        "depth": depth,
                        "status": status,
                        "title": title,
                        "h1": h1.strip(),
                        "meta_description": meta_description.strip(),
                        "load_ms": load_ms,
                        "screenshot_path": screenshot_path,
                        "error_type": error_type,
                        "error_detail": error_detail,
                        "redirect_chain": redirects,
                        "console": console,
                        "network": network,
                        "links": links,
                        "responsive": responsive,
                        "quality": quality if not error_type else {},
                    },
                )
                page_records.append(
                    {
                        "url": url,
                        "status": status,
                        "title": title,
                        "meta_description": meta_description,
                        "links": links,
                        "quality": quality if not error_type else {},
                    }
                )

                if error_type and options["page_health"]:
                    title_text = {
                        "timeout": "Page load timed out",
                        "cross_domain_redirect": "Cross-domain redirect blocked",
                    }.get(error_type, "Page could not be loaded")
                    findings.append(
                        {
                            "page_url": url,
                            "severity": "high",
                            "category": "page",
                            "title": title_text,
                            "detail": error_detail or "Navigation failed.",
                        }
                    )
                elif (status >= 400 or status == 0) and options["page_health"]:
                    findings.append(
                        {
                            "page_url": url,
                            "severity": "high",
                            "category": "page",
                            "title": "Page could not be loaded",
                            "detail": f"The page returned status {status or 'failed'}.",
                        }
                    )
                if not error_type:
                    if status < 400 and options["passive_security"]:
                        cookies = await context.cookies([final_url]) if page_count == 1 else []
                        findings.extend(passive_security_findings(
                            url,
                            final_url,
                            response_headers,
                            security_evidence,
                            cookies,
                            check_cookies=page_count == 1,
                        ))
                    if options["seo"] and not title.strip():
                        findings.append({"page_url": url, "severity": "medium", "category": "seo", "title": "Missing page title", "detail": "This page does not have a usable HTML title."})
                    if options["seo"] and not meta_description.strip():
                        findings.append({"page_url": url, "severity": "low", "category": "seo", "title": "Missing meta description", "detail": "This page does not expose a meta description."})
                    if options["performance"] and load_ms > 3000:
                        findings.append({"page_url": url, "severity": "medium", "category": "performance", "title": "Slow page load", "detail": f"The page took {load_ms} ms to reach DOM content loaded."})
                    if options["responsive"]:
                        findings.extend(responsive_findings(url, responsive))
                    if status < 400 and options["content_quality"]:
                        findings.extend(page_content_findings(url, quality, settings))
                if options["console"]:
                    for item in console:
                        findings.append(console_finding(url, item))
                if options["network"]:
                    for item in network:
                        if item.get("status") in {"timeout", "failed"} and item.get("url") == url:
                            continue
                        findings.append(network_finding(url, item))
                console_count += len(console)
                network_request_count += len(network)
                api_request_count += sum(item.get("resource_type") in {"fetch", "xhr"} for item in network)
                page_failed_requests = sum(network_request_failed(item) for item in network)
                page_actionable_failures = sum(network_request_actionable(item) for item in network)
                failed_request_count += page_failed_requests
                actionable_failed_request_count += page_actionable_failures
                ignored_failed_request_count += page_failed_requests - page_actionable_failures
                passed_request_count += len(network) - page_failed_requests
                live_score, live_health = calculate_health_score(
                    findings,
                    page_count,
                    network_request_count,
                    actionable_failed_request_count,
                    page_priorities=store.page_priority_map(scan_id),
                    scan_options=options,
                    content_checks=settings,
                    max_pages=max_pages,
                )
                store.update_scan(
                    scan_id,
                    summary={
                        "pages_scanned": page_count,
                        "findings": len(findings),
                        "console_errors": console_count,
                        "failed_requests": failed_request_count,
                        "actionable_failed_requests": actionable_failed_request_count,
                        "ignored_failed_requests": ignored_failed_request_count,
                        "network_requests": network_request_count,
                        "api_requests": api_request_count,
                        "passed_requests": passed_request_count,
                        "timeouts": timeout_count,
                        **health_summary_payload(live_score, live_health, score_enabled),
                        "responsive_viewports": responsive_viewport_count,
                        "responsive_issues": sum(item.get("category") == "responsive" for item in findings),
                        "accessibility_issues": sum(
                            item.get("category") == "accessibility"
                            and item.get("severity") != "info"
                            for item in findings
                        ),
                        "security_issues": sum(item.get("category") == "security" for item in findings),
                        "retried_pages": retried_page_count,
                        "recovered_pages": recovered_page_count,
                        "robots_policy": policy.status,
                        "rate_limit_ms": policy.rate_limit_ms,
                    },
                )
                for link in links:
                    if link not in visited and link not in queued:
                        queue.append((link, depth + 1))
                        queued.add(link)
            if options["content_quality"] or options["sitemap_indexing"]:
                quality_findings, analyzed_site = aggregate_quality_findings(
                    page_records,
                    sitemap,
                    policy,
                    settings,
                    normalized_root,
                )
                findings.extend(
                    finding
                    for finding in quality_findings
                    if (
                        finding.get("category") == "content"
                        and options["content_quality"]
                    ) or (
                        finding.get("category") == "indexing"
                        and options["sitemap_indexing"]
                    )
                )
                site_analysis = analyzed_site if options["sitemap_indexing"] else {}
            if options["template_intelligence"]:
                attach_template_metadata(findings, page_records)
            store.update_scan(scan_id, site_analysis=site_analysis)
            await browser.close()

        for finding in findings:
            store.save_finding(scan_id, finding)
        score, health_details = calculate_health_score(
            findings,
            page_count,
            network_request_count,
            actionable_failed_request_count,
            page_priorities=store.page_priority_map(scan_id),
            scan_options=options,
            content_checks=settings,
            max_pages=max_pages,
        )
        store.update_scan(
            scan_id,
            status="completed",
            completed_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            summary={
                "pages_scanned": page_count,
                "findings": len(findings),
                "console_errors": console_count,
                "failed_requests": failed_request_count,
                "actionable_failed_requests": actionable_failed_request_count,
                "ignored_failed_requests": ignored_failed_request_count,
                "network_requests": network_request_count,
                "api_requests": api_request_count,
                "passed_requests": passed_request_count,
                "timeouts": timeout_count,
                "robots_skipped": skipped_robots,
                "blocked_redirects": blocked_redirects,
                "retried_pages": retried_page_count,
                "recovered_pages": recovered_page_count,
                "robots_policy": policy.status,
                "robots_detail": policy.detail,
                "rate_limit_ms": policy.rate_limit_ms,
                **health_summary_payload(score, health_details, score_enabled),
                "responsive_viewports": responsive_viewport_count,
                "responsive_issues": sum(item.get("category") == "responsive" for item in findings),
                "accessibility_issues": sum(
                    item.get("category") == "accessibility"
                    and item.get("severity") != "info"
                    for item in findings
                ),
                "security_issues": sum(item.get("category") == "security" for item in findings),
                "content_issues": sum(item.get("category") == "content" for item in findings),
                "indexing_issues": sum(
                    item.get("category") == "indexing" and item.get("severity") != "info"
                    for item in findings
                ),
                "sitemap_urls": site_analysis.get("sitemap_url_count", 0),
            },
        )
    except Exception as error:
        store.update_scan(scan_id, status="failed", error=str(error)[:500])


def start_scan(
    scan_id: str,
    url: str,
    max_pages: int,
    max_depth: int,
    content_checks: dict | None = None,
    scan_options: dict | None = None,
) -> None:
    resume_event = asyncio.Event()
    resume_event.set()
    _SCAN_CONTROLS[scan_id] = ScanControl(resume_event=resume_event)
    task = asyncio.create_task(
        scan_website(scan_id, url, max_pages, max_depth, content_checks, scan_options)
    )
    _BACKGROUND_TASKS[scan_id] = task

    def cleanup(completed: asyncio.Task, current_scan_id: str = scan_id) -> None:
        if _BACKGROUND_TASKS.get(current_scan_id) is completed:
            _BACKGROUND_TASKS.pop(current_scan_id, None)
            _SCAN_CONTROLS.pop(current_scan_id, None)

    task.add_done_callback(cleanup)


def pause_scan(scan_id: str) -> bool:
    task = _BACKGROUND_TASKS.get(scan_id)
    control = _SCAN_CONTROLS.get(scan_id)
    if not task or task.done() or not control:
        return False
    control.resume_event.clear()
    store.update_scan(scan_id, status="paused")
    return True


def resume_scan(scan_id: str) -> bool:
    task = _BACKGROUND_TASKS.get(scan_id)
    control = _SCAN_CONTROLS.get(scan_id)
    if not task or task.done() or not control:
        return False
    control.resume_event.set()
    store.update_scan(scan_id, status="running")
    return True


async def cancel_scan(scan_id: str) -> None:
    task = _BACKGROUND_TASKS.get(scan_id)
    if not task or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    finally:
        _BACKGROUND_TASKS.pop(scan_id, None)
        _SCAN_CONTROLS.pop(scan_id, None)
