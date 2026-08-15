import hashlib
import re
from urllib.parse import urlsplit, urlunsplit


SEVERITY_RANK = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}
PRIORITY_RANK = {"critical": 3, "high_value": 2, "standard": 1}


def infer_page_priority(url: str) -> str:
    path = urlsplit(url).path.lower()
    critical_terms = ("/checkout", "/cart", "/payment", "/login", "/sign-in", "/signin", "/signup", "/sign-up", "/register", "/pricing")
    high_value_terms = ("/product", "/products", "/service", "/services", "/solutions", "/features", "/plans")
    if any(term in path for term in critical_terms):
        return "critical"
    if any(term in path for term in high_value_terms):
        return "high_value"
    return "standard"


def _request_url(finding: dict) -> str | None:
    match = re.search(r"\b(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(https?://\S+)", finding.get("detail", ""))
    return match.group(1).rstrip(".,") if match else finding.get("related_request_url")


def _stable_url(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
        path = re.sub(r"/\d{4,}(?=/|$)", "/:id", parsed.path)
        return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path.rstrip("/") or "/", "", ""))
    except ValueError:
        return value.split("?", 1)[0].lower()


def _network_classification(finding: dict) -> str:
    explicit = finding.get("classification")
    if explicit:
        return str(explicit)
    detail = finding.get("detail", "").lower()
    for value in (
        "advertising_analytics",
        "security_challenge",
        "third_party_functional",
        "first_party",
        "live_chat",
    ):
        if f"classification: {value.replace('_', ' ')}" in detail:
            return value
    title = finding.get("title", "").lower()
    if "analytics" in title:
        return "advertising_analytics"
    if "security challenge" in title:
        return "security_challenge"
    if "live chat" in title:
        return "live_chat"
    if "first-party" in title:
        return "first_party"
    if "third-party" in title:
        return "third_party_functional"
    return "unknown"


def finding_fingerprint(finding: dict) -> str:
    category = finding.get("category", "other").lower()
    title = re.sub(r"\s+", " ", finding.get("title", "").strip().lower())
    signature = f"{category}|{title}"
    explicit_metadata = finding.get("metadata") or finding
    if category == "network":
        signature += f"|{_network_classification(finding)}|{_stable_url(_request_url(finding))}"
    elif category == "console":
        message = re.sub(r"https?://\S+", ":url", finding.get("detail", "").lower())
        message = re.sub(r"\b\d{3,}\b", ":number", message)
        signature += f"|{re.sub(r'\\s+', ' ', message)[:180]}"
    elif category == "accessibility":
        rule_id = str(explicit_metadata.get("axe_rule_id", title))
        component = explicit_metadata.get("component_hint")
        selector = re.sub(
            r"(?:#[-\w]+|:nth-(?:child|of-type)\(\d+\))",
            ":element",
            str(explicit_metadata.get("affected_element", "")).lower(),
        )
        signature = f"{category}|{rule_id}|{component or selector[:160]}"
    return hashlib.sha1(signature.encode("utf-8")).hexdigest()[:16]


def finding_metadata(finding: dict) -> dict:
    category = finding.get("category", "other")
    title = finding.get("title", "")
    title_lower = title.lower()
    severity = finding.get("severity", "low")
    confidence = "likely"
    verification = "Observed during this browser scan. Recheck in a normal browser before changing production."
    owner = "Developer / QA"
    what_happened = finding.get("detail", "")
    why_it_matters = "This may affect the experience or reliability of the page."
    action = "Reproduce the issue, review the technical evidence, and fix or dismiss it with context."

    if category == "page":
        owner = "Developer / Website administrator"
        why_it_matters = "Visitors and search engines may be unable to reach this content."
        action = "Check the route or deployment. Restore the page, redirect it, or update every source link that points here."
        if "status 404" in finding.get("detail", "").lower() or "404" in finding.get("detail", ""):
            confidence = "confirmed"
            verification = "The server returned HTTP 404 after the crawler's retry."
        elif "timeout" in title_lower or "timed out" in finding.get("detail", "").lower():
            confidence = "needs_review"
            verification = "The automated browser timed out; verify from the same environment and from a normal browser."
    elif category == "seo":
        confidence = "confirmed"
        verification = "Confirmed by inspecting the rendered page metadata."
        owner = "SEO / Content"
        if "title" in title_lower:
            why_it_matters = "A missing title makes browser tabs and search results less clear."
            action = "Add a unique, descriptive HTML title for this page."
        elif "meta description" in title_lower:
            why_it_matters = "Search engines may generate a less useful search-result description."
            action = "Add a concise, page-specific meta description."
        elif "h1" in title_lower:
            why_it_matters = "Users and search engines lose a clear primary heading for the page."
            action = "Add one visible H1 that describes the page's main purpose."
    elif category == "performance":
        confidence = "likely"
        verification = "Measured in the scan browser; confirm with repeated runs or a performance profiler."
        owner = "Frontend / Performance developer"
        why_it_matters = "Slow loading can increase abandonment and reduce search performance."
        action = "Profile the page, then reduce blocking scripts, large assets, slow APIs, or excessive rendering work."
    elif category == "network":
        classification = _network_classification(finding)
        if classification == "first_party":
            confidence = "confirmed" if severity in {"critical", "high"} else "likely"
            owner = "Backend / Frontend developer"
            why_it_matters = "A product-owned resource or API did not respond successfully and may break page functionality."
            action = "Open the request evidence, reproduce it, and fix the endpoint, deployment, permissions, or client request."
        elif classification == "advertising_analytics":
            confidence = "likely"
            owner = "Marketing / Analytics"
            why_it_matters = "Tracking or advertising data may be incomplete, but core page behavior is usually unaffected."
            action = "Validate consent and analytics configuration in a normal browser; ignore scanner-only blocking when expected."
        elif classification == "security_challenge":
            confidence = "needs_review"
            owner = "Website administrator / Security"
            why_it_matters = "A bot-protection challenge was blocked or could not run in the scanner environment."
            action = "Verify the challenge manually. Adjust the integration only if real visitors experience the same failure."
        elif classification == "live_chat":
            confidence = "likely"
            owner = "Website administrator / Support"
            why_it_matters = "The support widget may not load, while the rest of the page can remain usable."
            action = "Check the widget configuration and vendor status in a normal browser."
        else:
            confidence = "likely"
            owner = "Developer / Third-party owner"
            why_it_matters = "A dependency failed and may affect the feature that relies on it."
            action = "Confirm the failure manually, then fix the integration or contact the third-party provider."
    elif category == "console":
        owner = "Frontend developer / QA"
        if "blocked security challenge" in title_lower:
            confidence = "confirmed"
            verification = "Matched to a security iframe blocked by the automated scan environment."
            why_it_matters = "This is usually scanner noise, not a website defect."
            action = "Ignore it unless the same warning appears for normal users or the protected feature fails."
        elif "linked to" in title_lower:
            confidence = "likely"
            verification = "Correlated with a failed request captured in the network log."
            why_it_matters = "The browser reported the same underlying network failure; it is supporting evidence, not a separate root cause."
            action = "Investigate the linked network request rather than treating this as a second issue."
        else:
            confidence = "needs_review"
            verification = "Captured from the browser console without a matching failed network request."
            why_it_matters = "Unhandled browser errors can indicate broken interactions or incorrect page code."
            action = "Reproduce the page interaction, inspect the stack trace, and fix the originating script."
    elif category == "responsive":
        confidence = "likely"
        verification = "Measured from the rendered page at the named viewport; confirm using the attached viewport screenshot."
        owner = "Frontend developer / QA"
        if "capture incomplete" in title_lower:
            confidence = "needs_review"
            why_it_matters = "One or more viewport checks or screenshots are missing from this scan."
            action = "Retry the scan and inspect browser stability if the responsive capture repeatedly fails."
        elif "horizontal overflow" in title_lower:
            why_it_matters = "Users may need to scroll sideways or may be unable to reach content and controls."
            action = "Inspect the listed overflowing elements and replace fixed widths with responsive sizing or wrapping."
        elif "overlap" in title_lower:
            why_it_matters = "Overlapping controls or text can hide information and prevent taps or clicks."
            action = "Review the listed element pair at this viewport and correct positioning, spacing, or stacking."
        elif "small text" in title_lower:
            why_it_matters = "Text below 12px can be difficult to read, especially on mobile devices."
            action = "Increase the affected text size and verify that the surrounding layout still reflows correctly."
        elif "navigation" in title_lower:
            confidence = "needs_review"
            why_it_matters = "Users may have no visible way to reach important sections of the website."
            action = "Verify that a usable mobile or tablet menu is visible, labelled, keyboard-accessible, and opens correctly."
        elif "images extend" in title_lower:
            why_it_matters = "Images outside the viewport can be clipped or create horizontal scrolling."
            action = "Constrain images with responsive dimensions such as max-width: 100% and check their containers."
        else:
            why_it_matters = "Primary content may be unavailable to users at this screen size."
            action = "Review the responsive CSS and ensure the primary heading and main content remain visible."
    elif category == "accessibility":
        confidence = "confirmed"
        verification = "Detected automatically by axe-core against the rendered DOM; manual accessibility testing is still required."
        owner = "Accessibility / Frontend developer"
        why_it_matters = "People using assistive technology may be unable to understand or operate the affected element."
        action = "Inspect the captured element and DOM evidence, apply the axe-core recommendation, and verify with keyboard and assistive-technology testing."
    elif category == "security":
        confidence = "confirmed"
        verification = "Observed without attack payloads by inspecting the loaded page, response headers, and first-party cookie settings."
        owner = "Website administrator / Developer"
        why_it_matters = "A missing preventive protection can make a successful attack easier or expose visitor information. It does not prove the website is currently compromised."
        if "https" in title_lower or "insecure connection" in title_lower:
            action = "Serve the page and every referenced resource over HTTPS, then redirect HTTP traffic to HTTPS."
        elif "browser security protections" in title_lower:
            action = "Ask the hosting or development team to add the listed response headers. Start with HSTS and Content-Security-Policy, then verify the site still works."
        elif "cookie" in title_lower:
            action = "Set Secure and HttpOnly on login or session cookies in the server configuration, then test sign-in and session behavior."
        elif "version" in title_lower:
            action = "Remove exact software versions from Server or X-Powered-By response headers and keep the underlying software patched."
        else:
            action = "Review the captured page evidence and apply the named preventive browser protection."
    elif category == "content":
        confidence = "confirmed"
        verification = "Confirmed from the rendered page content and same-domain link evidence captured by the scan."
        owner = "Content / SEO / Frontend"
        if "duplicate" in title_lower:
            why_it_matters = "Repeated metadata makes pages harder for users and search engines to distinguish."
            action = "Give each affected page a unique title or description that matches its purpose."
        elif "broken internal link" in title_lower:
            owner = "Content / Developer"
            why_it_matters = "Visitors following this link reach an error page and search crawlers waste crawl paths."
            action = "Update or remove every source link, restore the target, or add an appropriate redirect."
        elif "alternative text" in title_lower:
            why_it_matters = "People using screen readers may not understand the purpose of these images."
            action = "Add meaningful alt text to informative images and an empty alt attribute to decorative images."
        else:
            why_it_matters = "Thin, unfinished, or poorly structured content can reduce clarity, trust, accessibility, and search quality."
            action = "Review the captured evidence and improve the affected page content or heading structure."
    elif category == "indexing":
        confidence = "confirmed" if severity in {"high", "medium"} else "needs_review"
        verification = "Compared rendered indexability signals with the XML sitemap, internal links, canonical tags, and robots policy."
        owner = "SEO / Website administrator"
        why_it_matters = "Conflicting discovery and indexing signals can hide useful pages or waste search-engine crawl effort."
        if "orphan" in title_lower:
            action = "Add a relevant internal link to this page or remove it from the sitemap if it should not be discovered."
        elif "missing from sitemap" in title_lower:
            action = "Add the indexable page to the XML sitemap, or confirm that excluding it is intentional."
        elif "canonical" in title_lower:
            action = "Verify the canonical target and ensure it is absolute, indexable, same-domain when intended, and returns successfully."
        elif "noindex" in title_lower:
            action = "Remove the URL from the sitemap or remove noindex if the page should appear in search."
        else:
            action = "Align the sitemap, robots rules, internal links, and page indexability directives."
    elif category in {"crawler", "robots"}:
        confidence = "confirmed"
        owner = "Website administrator"
        why_it_matters = "Crawl policy or crawler limits can prevent parts of the site from being inspected."
        action = "Review robots.txt, redirects, and crawl limits before running another authorized scan."

    if severity == "info":
        severity_reason = "Informational evidence; it does not reduce the health score."
    elif severity in {"critical", "high"}:
        severity_reason = "High priority because it can block a page or important first-party functionality."
    elif severity == "medium":
        severity_reason = "Action recommended because users or a meaningful feature may be affected."
    else:
        severity_reason = "Lower impact; address during routine quality or content maintenance."

    return {
        "fingerprint": finding_fingerprint(finding),
        "confidence": confidence,
        "verification": verification,
        "owner": owner,
        "what_happened": what_happened,
        "why_it_matters": why_it_matters,
        "recommended_action": action,
        "severity_reason": severity_reason,
    }


def enrich_finding(finding: dict) -> dict:
    metadata = {**finding_metadata(finding), **(finding.get("metadata") or {})}
    result = {**finding, **metadata}
    result.pop("metadata_json", None)
    return result


def build_issue_groups(findings: list[dict]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for original in findings:
        finding = enrich_finding(original)
        if finding.get("severity") == "info":
            continue
        key = finding["fingerprint"]
        group = grouped.setdefault(
            key,
            {
                "group_id": key,
                "fingerprint": key,
                "severity": finding["severity"],
                "category": finding["category"],
                "title": finding["title"],
                "count": 0,
                "affected_pages": [],
                "finding_ids": [],
                "sample_detail": finding["detail"],
                "confidence": finding["confidence"],
                "verification": finding["verification"],
                "owner": finding["owner"],
                "what_happened": finding["what_happened"],
                "why_it_matters": finding["why_it_matters"],
                "recommended_action": finding["recommended_action"],
                "severity_reason": finding["severity_reason"],
                "page_priority": finding.get("page_priority", "standard"),
                "plain_problem": finding.get("plain_problem"),
                "plain_fix": finding.get("plain_fix"),
                "example_page_url": finding.get("page_url"),
                "example_element_label": finding.get("element_label"),
                "example_page_section": finding.get("page_section"),
                "example_affected_element": finding.get("affected_element"),
                "example_dom_evidence": finding.get("dom_evidence"),
                "example_element_screenshot_path": finding.get("element_screenshot_path"),
                "help_url": finding.get("help_url"),
                "axe_rule_id": finding.get("axe_rule_id"),
                "wcag_criteria": finding.get("wcag_criteria"),
                "wcag_level": finding.get("wcag_level"),
                "_template_pages": {},
                "_component_pages": {},
            },
        )
        group["count"] += 1
        if finding.get("id"):
            group["finding_ids"].append(finding["id"])
        page_url = finding.get("page_url")
        if page_url and page_url not in group["affected_pages"]:
            group["affected_pages"].append(page_url)
        template_label = finding.get("template_label")
        if template_label and page_url:
            structure_signature = finding.get("structure_signature") or "url-family"
            cluster_key = f"{template_label}|{structure_signature}"
            cluster = group["_template_pages"].setdefault(
                cluster_key,
                {
                    "label": template_label,
                    "pages": set(),
                    "dom_match": structure_signature != "url-family",
                },
            )
            cluster["pages"].add(page_url)
        component = finding.get("component_hint")
        if component and page_url:
            group["_component_pages"].setdefault(component, set()).add(page_url)
        if SEVERITY_RANK.get(finding["severity"], 0) > SEVERITY_RANK.get(group["severity"], 0):
            group["severity"] = finding["severity"]
        if PRIORITY_RANK.get(finding.get("page_priority", "standard"), 1) > PRIORITY_RANK.get(group["page_priority"], 1):
            group["page_priority"] = finding["page_priority"]
    for group in grouped.values():
        group["affected_pages"].sort()
        shared_candidates = [
            ("component", label, pages, True)
            for label, pages in group.pop("_component_pages").items()
            if len(pages) >= 2
        ]
        shared_candidates.extend(
            ("template", cluster["label"], cluster["pages"], cluster["dom_match"])
            for cluster in group.pop("_template_pages").values()
            if len(cluster["pages"]) >= 2
        )
        if shared_candidates:
            kind, label, pages, structural_match = max(
                shared_candidates,
                key=lambda item: len(item[2]),
            )
            confidence = (
                "high"
                if structural_match and len(pages) == len(group["affected_pages"])
                else "medium"
            )
            group["shared_origin"] = {
                "kind": kind,
                "label": label,
                "confidence": confidence,
                "affected_page_count": len(pages),
            }
            group["recommended_action"] = (
                f"Fix this once in the likely {label}, then verify all {len(pages)} affected pages. "
                f"{group['recommended_action']}"
            )
    return sorted(
        grouped.values(),
        key=lambda item: (
            -(SEVERITY_RANK.get(item["severity"], 0) * 10 + PRIORITY_RANK.get(item["page_priority"], 1)),
            -item["count"],
            item["title"],
        ),
    )


def compare_issue_groups(current: list[dict], baseline: list[dict]) -> dict:
    current_by_id = {item["fingerprint"]: item for item in current}
    baseline_by_id = {item["fingerprint"]: item for item in baseline}
    items = []
    for fingerprint in sorted(current_by_id.keys() | baseline_by_id.keys()):
        now = current_by_id.get(fingerprint)
        before = baseline_by_id.get(fingerprint)
        if now and not before:
            status = "new"
            item = dict(now)
        elif before and not now:
            status = "fixed"
            item = dict(before)
        else:
            assert now and before
            current_pages = set(now["affected_pages"])
            previous_pages = set(before["affected_pages"])
            status = "unchanged" if current_pages == previous_pages else "recurring"
            item = dict(now)
            item["previous_affected_pages"] = before["affected_pages"]
        item["change_status"] = status
        items.append(item)
    order = {"new": 0, "recurring": 1, "fixed": 2, "unchanged": 3}
    items.sort(key=lambda item: (order[item["change_status"]], -SEVERITY_RANK.get(item["severity"], 0), item["title"]))
    counts = {name: sum(item["change_status"] == name for item in items) for name in order}
    return {"counts": counts, "items": items}
