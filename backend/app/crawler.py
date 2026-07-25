import asyncio
import posixpath
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from . import store

SCREENSHOTS = Path(__file__).resolve().parents[1] / "data" / "screenshots"
USER_AGENT = "BugBusterWebsiteExplorer/0.2"
NAVIGATION_TIMEOUT_MS = 30_000
DEFAULT_RATE_LIMIT_MS = 750
MAX_ROBOTS_DELAY_SECONDS = 10
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "dclid", "msclkid"}


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


async def scan_website(scan_id: str, root_url: str, max_pages: int, max_depth: int) -> None:
    store.update_scan(scan_id, status="running")
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    normalized_root = normalize_url(root_url)
    queue = deque([(normalized_root, 0)])
    queued = {normalized_root}
    visited: set[str] = set()
    page_count = console_count = failed_request_count = timeout_count = 0
    skipped_robots = blocked_redirects = 0
    findings: list[dict] = []
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1440, "height": 900},
                ignore_https_errors=False,
                user_agent=USER_AGENT,
            )
            policy = await load_robots_policy(context, normalized_root)
            if policy.disallow_all:
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
                url, depth = queue.popleft()
                queued.discard(url)
                if url in visited or depth > max_depth:
                    continue
                visited.add(url)
                if not policy.allows(url):
                    skipped_robots += 1
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
                page = await context.new_page()
                page.on(
                    "console",
                    lambda message: console.append({"level": message.type, "message": message.text})
                    if message.type in {"error", "warning"}
                    else None,
                )
                def capture_response(response: object) -> None:
                    if response.status >= 400:
                        network.append({"method": response.request.method, "url": response.url, "status": response.status})
                    if 300 <= response.status < 400 and response.request.is_navigation_request():
                        redirects.append(
                            {
                                "from": response.url,
                                "status": response.status,
                                "to": urljoin(response.url, response.headers.get("location", "")),
                            }
                        )

                page.on("response", capture_response)

                async def enforce_navigation_boundary(route: object) -> None:
                    if route.request.is_navigation_request() and not same_site(route.request.url, normalized_root):
                        await route.abort("blockedbyclient")
                    else:
                        await route.continue_()

                await page.route("**/*", enforce_navigation_boundary)
                started = perf_counter()
                last_navigation_started = started
                status, title, h1, meta_description, links = 0, "", "", "", []
                screenshot_path = None
                final_url = url
                error_type = error_detail = None
                try:
                    response = await page.goto(url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
                    final_url = normalize_url(page.url)
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
                                meta_description: document.querySelector('meta[name="description"]')?.getAttribute('content') || '',
                                links: [...document.querySelectorAll('a[href]')].map(node => node.href),
                            })"""
                        )
                        title = page_data["title"]
                        h1 = page_data["h1"]
                        meta_description = page_data["meta_description"]
                        links = sorted(
                            {
                                normalize_url(item)
                                for item in page_data["links"]
                                if same_site(item, normalized_root)
                            }
                        )
                        filename = f"{scan_id}-{page_count + 1}.png"
                        await page.screenshot(path=str(SCREENSHOTS / filename), full_page=True)
                        screenshot_path = filename
                except PlaywrightTimeoutError:
                    timeout_count += 1
                    error_type = "timeout"
                    error_detail = f"Navigation did not reach DOM content loaded within {NAVIGATION_TIMEOUT_MS:,} ms."
                    network.append({"method": "GET", "url": url, "status": "timeout", "error": error_detail})
                except Exception as error:
                    error_type = "navigation_error"
                    error_detail = str(error)[:300]
                    network.append({"method": "GET", "url": url, "status": "failed", "error": error_detail})

                load_ms = round((perf_counter() - started) * 1000)
                page_count += 1
                await page.close()
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
                    },
                )

                if error_type:
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
                elif status >= 400 or status == 0:
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
                    if not title.strip():
                        findings.append({"page_url": url, "severity": "medium", "category": "seo", "title": "Missing page title", "detail": "This page does not have a usable HTML title."})
                    if not meta_description.strip():
                        findings.append({"page_url": url, "severity": "low", "category": "seo", "title": "Missing meta description", "detail": "This page does not expose a meta description."})
                    if not h1.strip():
                        findings.append({"page_url": url, "severity": "low", "category": "seo", "title": "Missing H1 heading", "detail": "This page does not contain a visible H1 heading."})
                    if load_ms > 3000:
                        findings.append({"page_url": url, "severity": "medium", "category": "performance", "title": "Slow page load", "detail": f"The page took {load_ms} ms to reach DOM content loaded."})
                for item in console:
                    findings.append({"page_url": url, "severity": "medium", "category": "console", "title": f"Browser {item['level']}", "detail": item["message"][:500]})
                for item in network:
                    if item.get("status") in {"timeout", "failed"} and item.get("url") == url:
                        continue
                    findings.append({"page_url": url, "severity": "high", "category": "network", "title": "Failed network request", "detail": f"{item.get('method', 'GET')} {item.get('url')} returned {item.get('status')}."})
                console_count += len(console)
                failed_request_count += len(network)
                for link in links:
                    if link not in visited and link not in queued:
                        queue.append((link, depth + 1))
                        queued.add(link)
            await browser.close()

        for finding in findings:
            store.save_finding(scan_id, finding)
        score = max(0, 100 - len(findings) * 3 - failed_request_count * 4)
        store.update_scan(
            scan_id,
            status="completed",
            completed_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            summary={
                "pages_scanned": page_count,
                "findings": len(findings),
                "console_errors": console_count,
                "failed_requests": failed_request_count,
                "timeouts": timeout_count,
                "robots_skipped": skipped_robots,
                "blocked_redirects": blocked_redirects,
                "robots_policy": policy.status,
                "robots_detail": policy.detail,
                "rate_limit_ms": policy.rate_limit_ms,
                "health_score": score,
            },
        )
    except Exception as error:
        store.update_scan(scan_id, status="failed", error=str(error)[:500])


_BACKGROUND_TASKS: set[asyncio.Task] = set()


def start_scan(scan_id: str, url: str, max_pages: int, max_depth: int) -> None:
    task = asyncio.create_task(scan_website(scan_id, url, max_pages, max_depth))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
