from __future__ import annotations

from .insights import infer_page_priority


HEALTH_METHOD_VERSION = "2.0"
SEVERITY_WEIGHTS = {"critical": 8.0, "high": 5.0, "medium": 3.0, "low": 1.0, "info": 0.0}
PAGE_PRIORITY_MULTIPLIERS = {"critical": 3.0, "high_value": 2.0, "standard": 1.0}
CATEGORY_WEIGHTS = {
    "reliability": 30.0,
    "performance": 15.0,
    "seo": 15.0,
    "accessibility": 15.0,
    "content": 15.0,
    "responsive": 10.0,
}
CATEGORY_LABELS = {
    "reliability": "Reliability",
    "performance": "Performance",
    "seo": "SEO and indexing",
    "accessibility": "Accessibility",
    "content": "Content quality",
    "responsive": "Responsive experience",
}
FINDING_CATEGORIES = {
    "page": "reliability",
    "crawler": "reliability",
    "robots": "reliability",
    "network": "reliability",
    "console": "reliability",
    "performance": "performance",
    "seo": "seo",
    "indexing": "seo",
    "accessibility": "accessibility",
    "content": "content",
    "responsive": "responsive",
}
CONTENT_CHECK_KEYS = (
    "duplicate_titles",
    "duplicate_descriptions",
    "headings",
    "broken_internal_links",
    "empty_pages",
    "placeholder_text",
    "short_content",
    "missing_image_alt",
    "canonical_tags",
)


def _option(options: dict | None, key: str) -> bool:
    if not options:
        return True
    return bool(options.get(key, False))


def _content_coverage(options: dict | None, checks: dict | None) -> float:
    if not _option(options, "content_quality"):
        return 0.0
    if not checks:
        return 1.0
    enabled = sum(bool(checks.get(key, True)) for key in CONTENT_CHECK_KEYS)
    return enabled / len(CONTENT_CHECK_KEYS)


def category_coverage(scan_options: dict | None, content_checks: dict | None) -> dict[str, float]:
    canonical_enabled = _content_coverage(scan_options, content_checks) > 0 and (
        not content_checks or bool(content_checks.get("canonical_tags", True))
    )
    return {
        "reliability": (
            (0.60 if _option(scan_options, "page_health") else 0.0)
            + (0.25 if _option(scan_options, "network") else 0.0)
            + (0.15 if _option(scan_options, "console") else 0.0)
        ),
        "performance": 1.0 if _option(scan_options, "performance") else 0.0,
        "seo": (
            (0.60 if _option(scan_options, "seo") else 0.0)
            + (0.25 if _option(scan_options, "sitemap_indexing") else 0.0)
            + (0.15 if canonical_enabled else 0.0)
        ),
        "accessibility": 1.0 if _option(scan_options, "accessibility") else 0.0,
        "content": _content_coverage(scan_options, content_checks),
        "responsive": 1.0 if _option(scan_options, "responsive") else 0.0,
    }


def _finding_enabled(finding: dict, options: dict | None, checks: dict | None) -> bool:
    category = str(finding.get("category", ""))
    option_by_category = {
        "page": "page_health",
        "crawler": "page_health",
        "robots": "page_health",
        "network": "network",
        "console": "console",
        "performance": "performance",
        "seo": "seo",
        "accessibility": "accessibility",
        "content": "content_quality",
        "responsive": "responsive",
    }
    if category in option_by_category and not _option(options, option_by_category[category]):
        return False
    if category == "indexing":
        canonical_enabled = _content_coverage(options, checks) > 0 and (
            not checks or bool(checks.get("canonical_tags", True))
        )
        return _option(options, "sitemap_indexing") or canonical_enabled
    return category in FINDING_CATEGORIES


def calculate_health_score(
    findings: list[dict],
    pages_scanned: int,
    network_requests: int = 0,
    failed_requests: int = 0,
    *,
    page_priorities: dict[str, str] | None = None,
    scan_options: dict | None = None,
    content_checks: dict | None = None,
    max_pages: int | None = None,
) -> tuple[int, dict]:
    """Return BugBuster Health Score v2 and its explainable scoring details."""
    page_total = max(1, pages_scanned)
    priorities = page_priorities or {}
    coverage_by_category = category_coverage(scan_options, content_checks)
    risks: dict[str, list[dict]] = {key: [] for key in CATEGORY_WEIGHTS}

    for finding in findings:
        if not _finding_enabled(finding, scan_options, content_checks):
            continue
        if finding.get("category") == "console" and finding.get("related_request_url"):
            continue
        category = FINDING_CATEGORIES.get(str(finding.get("category", "")))
        if not category or coverage_by_category[category] <= 0:
            continue
        severity = str(finding.get("severity", "low"))
        severity_weight = SEVERITY_WEIGHTS.get(severity, 1.0)
        if severity_weight <= 0:
            continue
        page_url = str(finding.get("page_url") or "")
        priority = str(finding.get("page_priority") or priorities.get(page_url) or infer_page_priority(page_url))
        multiplier = PAGE_PRIORITY_MULTIPLIERS.get(priority, 1.0)
        risk = severity_weight * multiplier
        risks[category].append({
            "category": category,
            "category_label": CATEGORY_LABELS[category],
            "title": str(finding.get("title") or "Website issue"),
            "page_url": page_url,
            "severity": severity,
            "page_priority": priority,
            "priority_multiplier": multiplier,
            "risk_points": round(risk, 1),
        })

    observed_network_failures = len([
        item for item in findings
        if item.get("category") == "network" and SEVERITY_WEIGHTS.get(str(item.get("severity", "info")), 0) > 0
    ])
    if _option(scan_options, "network") and failed_requests > observed_network_failures:
        for _ in range(failed_requests - observed_network_failures):
            risks["reliability"].append({
                "category": "reliability",
                "category_label": CATEGORY_LABELS["reliability"],
                "title": "Actionable network request failed",
                "page_url": "",
                "severity": "medium",
                "page_priority": "standard",
                "priority_multiplier": 1.0,
                "risk_points": 3.0,
            })

    categories: dict[str, dict] = {}
    total_effective_weight = 0.0
    for key, weight in CATEGORY_WEIGHTS.items():
        coverage = min(1.0, coverage_by_category[key])
        effective_weight = weight * coverage
        total_effective_weight += effective_weight
        category_risks = risks[key]
        total_risk = sum(item["risk_points"] for item in category_risks)
        peak_risk = max((item["risk_points"] for item in category_risks), default=0.0)
        prevalence_risk = min(1.0, total_risk / (page_total * 8.0))
        peak_risk_ratio = min(1.0, peak_risk / 24.0)
        risk_ratio = min(1.0, prevalence_risk * 0.70 + peak_risk_ratio * 0.30)
        category_score = round(100.0 * (1.0 - risk_ratio)) if effective_weight else None
        categories[key] = {
            "label": CATEGORY_LABELS[key],
            "score": category_score,
            "checked": effective_weight > 0,
            "coverage_percent": round(coverage * 100),
            "weight": weight,
            "effective_weight": round(effective_weight, 1),
            "finding_count": len(category_risks),
            "risk_points": round(total_risk, 1),
            "deduction": 0.0,
        }

    if total_effective_weight:
        score_value = sum(
            category["score"] * category["effective_weight"]
            for category in categories.values()
            if category["score"] is not None
        ) / total_effective_weight
        score = round(max(0.0, min(100.0, score_value)))
        for category in categories.values():
            if category["score"] is not None:
                category["deduction"] = round(
                    (100.0 - category["score"]) * category["effective_weight"] / total_effective_weight,
                    1,
                )
    else:
        score = 100

    scope_percent = round(total_effective_weight)
    reached_page_limit = bool(max_pages and pages_scanned >= max_pages)
    if reached_page_limit:
        confidence = "limited"
        reason = "The scan reached its page limit, so additional pages may exist outside this result."
    elif scope_percent >= 80:
        confidence = "comprehensive"
        reason = "Most quality areas were checked and the crawl finished below its page limit."
    elif scope_percent >= 50:
        confidence = "standard"
        reason = "The score covers the selected core checks; optional quality areas were not all included."
    else:
        confidence = "focused"
        reason = "This score represents a focused scan because several quality areas were not selected."

    all_impacts = sorted(
        (item for category_risks in risks.values() for item in category_risks),
        key=lambda item: (-item["risk_points"], item["title"], item["page_url"]),
    )
    priority_counts = {"critical": 0, "high_value": 0, "standard": 0}
    for priority in priorities.values():
        priority_counts[priority if priority in priority_counts else "standard"] += 1

    return score, {
        "method_version": HEALTH_METHOD_VERSION,
        "categories": categories,
        "coverage": {
            "scope_percent": scope_percent,
            "confidence": confidence,
            "reason": reason,
            "pages_scanned": pages_scanned,
            "page_limit": max_pages,
            "reached_page_limit": reached_page_limit,
            "important_pages": priority_counts,
        },
        "top_impacts": all_impacts[:3],
        "deductions": {key: value["deduction"] for key, value in categories.items()},
        "formula": "Severity weight × page-importance multiplier, normalized by pages and selected checks.",
    }


def health_summary_payload(score: int, details: dict, enabled: bool = True) -> dict:
    return {
        "health_score": score if enabled else None,
        "health_score_available": enabled,
        "health_method_version": details["method_version"],
        "health_categories": details["categories"],
        "health_coverage": details["coverage"],
        "health_top_impacts": details["top_impacts"],
        "health_breakdown": details["deductions"],
    }
