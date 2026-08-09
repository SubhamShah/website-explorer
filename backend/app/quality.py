import re
from collections import defaultdict
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree


DEFAULT_CONTENT_CHECKS = {
    "duplicate_titles": True,
    "duplicate_descriptions": True,
    "headings": True,
    "broken_internal_links": True,
    "empty_pages": True,
    "placeholder_text": True,
    "short_content": True,
    "missing_image_alt": True,
    "canonical_tags": True,
    "short_content_words": 100,
}

PLACEHOLDER_PATTERN = re.compile(
    r"\b(lorem ipsum|placeholder text|coming soon|under construction|todo:|sample text|dummy text)\b",
    re.IGNORECASE,
)


def parse_sitemap_document(xml_text: str) -> tuple[list[str], list[str]]:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return [], []
    root_name = root.tag.rsplit("}", 1)[-1].lower()
    locations = [
        (node.text or "").strip()
        for node in root.iter()
        if node.tag.rsplit("}", 1)[-1].lower() == "loc" and (node.text or "").strip()
    ]
    return ([], locations) if root_name == "sitemapindex" else (locations, [])


def robots_sitemap_locations(robots_text: str, root_url: str) -> list[str]:
    locations = []
    for line in robots_text.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip().lower() == "sitemap" and value.strip():
            locations.append(urljoin(root_url, value.strip()))
    return locations


def _same_origin(candidate: str, root_url: str) -> bool:
    try:
        candidate_url = urlparse(candidate)
        root = urlparse(root_url)
        return (
            candidate_url.scheme.lower(),
            candidate_url.hostname,
            candidate_url.port,
        ) == (root.scheme.lower(), root.hostname, root.port)
    except ValueError:
        return False


async def discover_sitemap_urls(context: object, root_url: str, max_documents: int = 8, max_urls: int = 5000) -> dict:
    sources = []
    queue = [urljoin(root_url, "/sitemap.xml")]
    try:
        robots_url = urljoin(root_url, "/robots.txt")
        robots_response = await context.request.get(robots_url, timeout=10_000, fail_on_status_code=False)
        if robots_response.status == 200:
            queue = robots_sitemap_locations(await robots_response.text(), root_url) + queue
    except Exception:
        pass
    queued = set(queue)
    visited = set()
    urls = set()
    errors = []
    while queue and len(visited) < max_documents and len(urls) < max_urls:
        sitemap_url = queue.pop(0)
        if sitemap_url in visited or not _same_origin(sitemap_url, root_url):
            continue
        visited.add(sitemap_url)
        try:
            response = await context.request.get(sitemap_url, timeout=15_000, fail_on_status_code=False)
            if response.status != 200:
                errors.append({"url": sitemap_url, "status": response.status})
                continue
            page_urls, nested_sitemaps = parse_sitemap_document(await response.text())
            sources.append(sitemap_url)
            urls.update(url for url in page_urls if _same_origin(url, root_url))
            for nested in nested_sitemaps:
                if nested not in queued and _same_origin(nested, root_url):
                    queue.append(nested)
                    queued.add(nested)
        except Exception as error:
            errors.append({"url": sitemap_url, "status": "failed", "detail": str(error)[:160]})
    return {
        "sources": sources,
        "urls": sorted(urls)[:max_urls],
        "errors": errors,
        "truncated": len(urls) >= max_urls or bool(queue),
    }


def page_content_findings(page_url: str, page_data: dict, settings: dict) -> list[dict]:
    findings = []
    word_count = int(page_data.get("word_count", 0))
    h1_count = int(page_data.get("h1_count", 0))
    canonical_urls = page_data.get("canonical_urls", [])
    if settings.get("headings", True):
        if h1_count == 0:
            findings.append({"page_url": page_url, "severity": "low", "category": "content", "title": "Missing H1 heading", "detail": "The rendered page does not contain an H1 heading."})
        elif h1_count > 1:
            findings.append({"page_url": page_url, "severity": "medium", "category": "content", "title": "Multiple H1 headings", "detail": f"The rendered page contains {h1_count} H1 headings."})
    if settings.get("empty_pages", True) and word_count < 10:
        findings.append({"page_url": page_url, "severity": "high", "category": "content", "title": "Page has almost no content", "detail": f"Only {word_count} visible words were detected."})
    elif settings.get("short_content", True) and word_count < int(settings.get("short_content_words", 100)):
        findings.append({"page_url": page_url, "severity": "low", "category": "content", "title": "Extremely short content", "detail": f"The page contains {word_count} visible words; the configured minimum is {settings.get('short_content_words', 100)}."})
    placeholder_matches = page_data.get("placeholder_matches", [])
    if settings.get("placeholder_text", True) and placeholder_matches:
        findings.append({"page_url": page_url, "severity": "medium", "category": "content", "title": "Placeholder text is visible", "detail": f"Detected: {', '.join(placeholder_matches[:5])}."})
    missing_alt = page_data.get("images_missing_alt", [])
    if settings.get("missing_image_alt", True) and missing_alt:
        findings.append({"page_url": page_url, "severity": "medium", "category": "content", "title": "Images are missing alternative text", "detail": f"{page_data.get('images_missing_alt_count', len(missing_alt))} rendered images have no alt text. Examples: {'; '.join(missing_alt[:5])}"})
    if settings.get("canonical_tags", True):
        if len(canonical_urls) > 1:
            findings.append({"page_url": page_url, "severity": "medium", "category": "indexing", "title": "Multiple canonical tags", "detail": f"Found {len(canonical_urls)} canonical URLs: {'; '.join(canonical_urls[:5])}"})
        elif canonical_urls:
            canonical = canonical_urls[0]
            if not canonical.startswith(("http://", "https://")):
                findings.append({"page_url": page_url, "severity": "high", "category": "indexing", "title": "Invalid canonical URL", "detail": f"The canonical value is not an absolute HTTP URL: {canonical}"})
            elif not _same_origin(canonical, page_url):
                findings.append({"page_url": page_url, "severity": "high", "category": "indexing", "title": "Canonical points outside the website", "detail": f"The page canonical points to {canonical}."})
            elif canonical.rstrip("/") != page_url.rstrip("/"):
                findings.append({"page_url": page_url, "severity": "low", "category": "indexing", "title": "Canonical points to a different page", "detail": f"Verify that this intentional consolidation is correct: {canonical}"})
    if settings.get("indexing", True) and page_data.get("noindex"):
        findings.append({"page_url": page_url, "severity": "info", "category": "indexing", "title": "Page is marked noindex", "detail": "The rendered robots directives tell search engines not to index this page."})
    return findings


def aggregate_quality_findings(
    pages: list[dict],
    sitemap: dict,
    policy: object,
    settings: dict,
    root_url: str,
) -> tuple[list[dict], dict]:
    findings = []
    crawled_by_url = {page["url"]: page for page in pages}
    crawled_urls = set(crawled_by_url)
    sitemap_urls = set(sitemap.get("urls", []))
    sources_by_url: dict[str, set[str]] = defaultdict(set)
    for page in pages:
        for link in page.get("links", []):
            sources_by_url[link].add(page["url"])

    def duplicates(field: str, title: str) -> None:
        values: dict[str, list[str]] = defaultdict(list)
        for page in pages:
            if page.get("status", 0) >= 400:
                continue
            value = " ".join(str(page.get(field, "")).lower().split())
            if value:
                values[value].append(page["url"])
        for urls in values.values():
            if len(urls) > 1:
                for url in urls:
                    findings.append({"page_url": url, "severity": "medium", "category": "content", "title": title, "detail": f"The same value appears on {len(urls)} pages: {'; '.join(urls[:8])}"})

    if settings.get("duplicate_titles", True):
        duplicates("title", "Duplicate page title")
    if settings.get("duplicate_descriptions", True):
        duplicates("meta_description", "Duplicate meta description")

    broken_internal = []
    if settings.get("broken_internal_links", True):
        for url, page in crawled_by_url.items():
            if page.get("status", 0) >= 400 and sources_by_url.get(url):
                broken_internal.append(url)
                findings.append({"page_url": url, "severity": "high", "category": "content", "title": "Broken internal link", "detail": f"The URL returned {page['status']} and is linked from {len(sources_by_url[url])} crawled pages."})

    internally_linked = set(sources_by_url)
    linked_missing_sitemap = sorted(internally_linked - sitemap_urls) if sitemap_urls else []
    orphan_pages = sorted(url for url in crawled_urls & sitemap_urls if url != root_url and not sources_by_url.get(url))
    sitemap_errors = [
        {"url": url, "status": crawled_by_url[url].get("status")}
        for url in sorted(sitemap_urls & crawled_urls)
        if crawled_by_url[url].get("status", 0) >= 400
    ]
    robots_blocked = sorted(url for url in sitemap_urls if not policy.allows(url))
    noindex_pages = sorted(page["url"] for page in pages if page.get("quality", {}).get("noindex"))
    noindex_in_sitemap = sorted(set(noindex_pages) & sitemap_urls)
    sitemap_sources = sitemap.get("sources", [])
    sitemap_request_errors = sitemap.get("errors", [])

    if sitemap_urls:
        sitemap_status = "valid"
        sitemap_status_detail = (
            f"Parsed {len(sitemap_urls)} page URL{'s' if len(sitemap_urls) != 1 else ''} "
            f"from {len(sitemap_sources)} XML sitemap source{'s' if len(sitemap_sources) != 1 else ''}."
        )
    elif sitemap_sources:
        sitemap_status = "empty_or_invalid"
        sitemap_status_detail = (
            "A sitemap address responded successfully, but it contained no valid page URLs. "
            "It may be empty XML or an HTML page returned instead of an XML sitemap."
        )
    elif sitemap_request_errors:
        statuses = {str(item.get("status", "")).lower() for item in sitemap_request_errors}
        if statuses and statuses <= {"404"}:
            sitemap_status = "not_found"
            sitemap_status_detail = "No XML sitemap was found; every sitemap address checked returned 404."
        else:
            sitemap_status = "unavailable"
            sitemap_status_detail = "The sitemap could not be read because the sitemap requests failed."
    else:
        sitemap_status = "not_found"
        sitemap_status_detail = "No XML sitemap was discovered for this website."
    sitemap_comparison_available = bool(sitemap_urls)

    if sitemap_status == "empty_or_invalid":
        findings.append({
            "page_url": root_url,
            "severity": "medium",
            "category": "indexing",
            "title": "Sitemap is empty or invalid",
            "detail": sitemap_status_detail,
        })
    elif sitemap_status == "not_found":
        findings.append({
            "page_url": root_url,
            "severity": "low",
            "category": "indexing",
            "title": "XML sitemap not found",
            "detail": sitemap_status_detail,
        })
    elif sitemap_status == "unavailable":
        findings.append({
            "page_url": root_url,
            "severity": "low",
            "category": "indexing",
            "title": "XML sitemap could not be checked",
            "detail": sitemap_status_detail,
        })

    for url in linked_missing_sitemap:
        findings.append({"page_url": url, "severity": "low", "category": "indexing", "title": "Internally linked page missing from sitemap", "detail": "This URL is linked by a crawled page but is not listed in the XML sitemap."})
    for url in orphan_pages:
        findings.append({"page_url": url, "severity": "medium", "category": "indexing", "title": "Orphan page", "detail": "This sitemap URL was crawled but no crawled page links to it internally."})
    for item in sitemap_errors:
        findings.append({"page_url": item["url"], "severity": "high", "category": "indexing", "title": "Sitemap URL returns an error", "detail": f"The sitemap URL returned status {item['status']}."})
    for url in robots_blocked[:200]:
        findings.append({"page_url": url, "severity": "medium", "category": "indexing", "title": "Sitemap URL blocked by robots.txt", "detail": "The XML sitemap lists this URL, but the published robots policy disallows crawling it."})
    for url in noindex_in_sitemap:
        findings.append({"page_url": url, "severity": "medium", "category": "indexing", "title": "Noindex page listed in sitemap", "detail": "The XML sitemap requests discovery of this URL, but the page tells search engines not to index it."})

    analysis = {
        "sitemap_sources": sitemap_sources,
        "sitemap_errors": sitemap_request_errors,
        "sitemap_truncated": sitemap.get("truncated", False),
        "sitemap_status": sitemap_status,
        "sitemap_status_detail": sitemap_status_detail,
        "sitemap_comparison_available": sitemap_comparison_available,
        "sitemap_url_count": len(sitemap_urls),
        "sitemap_urls_crawled": len(sitemap_urls & crawled_urls),
        "sitemap_urls_unchecked": len(sitemap_urls - crawled_urls),
        "crawled_url_count": len(crawled_urls),
        "orphan_page_count": len(orphan_pages),
        "orphan_pages": orphan_pages[:200],
        "linked_missing_sitemap_count": len(linked_missing_sitemap),
        "linked_missing_sitemap": linked_missing_sitemap[:200],
        "sitemap_page_error_count": len(sitemap_errors),
        "sitemap_page_errors": sitemap_errors[:200],
        "robots_blocked_sitemap_count": len(robots_blocked),
        "robots_blocked_sitemap": robots_blocked[:200],
        "noindex_page_count": len(noindex_pages),
        "noindex_pages": noindex_pages[:200],
        "noindex_in_sitemap_count": len(noindex_in_sitemap),
        "noindex_in_sitemap": noindex_in_sitemap[:200],
        "broken_internal_link_count": len(broken_internal),
        "broken_internal_links": broken_internal[:200],
    }
    return findings, analysis
