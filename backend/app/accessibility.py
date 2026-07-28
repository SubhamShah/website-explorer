import re
from pathlib import Path


AXE_OPTIONS = {
    "runOnly": {
        "type": "tag",
        "values": [
            "wcag2a",
            "wcag2aa",
            "wcag21a",
            "wcag21aa",
            "wcag22a",
            "wcag22aa",
            "best-practice",
        ],
    },
    "resultTypes": ["violations"],
    "selectors": True,
    "iframes": True,
}

IMPACT_SEVERITY = {
    "critical": "critical",
    "serious": "high",
    "moderate": "medium",
    "minor": "low",
}

PLAIN_LANGUAGE_IMPACTS = {
    "button-name": "Screen-reader users may not know what this button does.",
    "color-contrast": "People with low vision may be unable to read this text against its background.",
    "document-title": "Screen-reader and keyboard users may have difficulty identifying this browser tab.",
    "form-field-multiple-labels": "Assistive technology may announce confusing or duplicated instructions for this field.",
    "html-has-lang": "Screen readers may pronounce the page using the wrong language.",
    "image-alt": "People who cannot see this image may miss its meaning or purpose.",
    "input-button-name": "Screen-reader users may not understand the purpose of this form control.",
    "label": "Screen-reader users may not know what information this form field requires.",
    "link-name": "Screen-reader users may not know where this link goes.",
    "region": "Screen-reader users may have difficulty navigating this content by landmarks.",
}

PLAIN_LANGUAGE_PROBLEMS = {
    "button-name": "This button has no name that a screen reader can announce.",
    "color-contrast": "This text does not have enough contrast against its background.",
    "document-title": "This page does not have a useful browser-tab title.",
    "form-field-multiple-labels": "This form field has more than one label, which can be announced confusingly.",
    "html-has-lang": "The page does not identify its main language.",
    "image-alt": "This image has no text alternative describing its meaning.",
    "input-button-name": "This form control has no name that a screen reader can announce.",
    "label": "This form field does not have a clear label.",
    "link-name": "This link has no meaningful name or link text.",
    "region": "This content is not contained in a clearly named page region.",
}

PLAIN_LANGUAGE_FIXES = {
    "button-name": "Give the button visible text or a short aria-label that describes its action, such as “Submit answer”.",
    "color-contrast": "Use a darker text color or lighter background until the text meets the required contrast ratio.",
    "document-title": "Add a short, unique <title> that identifies this page.",
    "form-field-multiple-labels": "Keep one clear label and remove or correctly associate any duplicate labels.",
    "html-has-lang": "Add the correct language to the <html> element, such as lang=\"en\".",
    "image-alt": "Add a short, meaningful alt description; use alt=\"\" only when the image is decorative.",
    "input-button-name": "Add visible text, a value, or an aria-label that clearly describes this control.",
    "label": "Add a visible <label> connected to this field, or add a clear aria-label when a visible label is not possible.",
    "link-name": "Give the link meaningful visible text or an aria-label that explains where it goes.",
    "region": "Place this content inside an appropriate landmark such as main, nav, header, or footer.",
}


def load_axe_source() -> str:
    try:
        from axe_playwright_python.sync_playwright import Axe
    except ImportError as error:
        raise RuntimeError(
            "axe-playwright-python is not installed; install the backend requirements."
        ) from error
    return Axe().axe_script


def wcag_metadata(tags: list[str]) -> tuple[list[str], str]:
    criteria = []
    level = "Best practice"
    for tag in tags:
        match = re.fullmatch(r"wcag(\d)(\d)(\d)", tag.lower())
        if match:
            criterion = ".".join(match.groups())
            if criterion not in criteria:
                criteria.append(criterion)
        level_match = re.fullmatch(r"wcag(?:2|21|22)(a{1,3})", tag.lower())
        if level_match:
            candidate = level_match.group(1).upper()
            if len(candidate) > len(level.replace("Level ", "")) or level == "Best practice":
                level = f"Level {candidate}"
    return criteria, level


def component_hint(selector: str) -> str | None:
    lowered = selector.lower()
    if "header" in lowered:
        return "shared header component"
    if "nav" in lowered or "menu" in lowered:
        return "shared navigation component"
    if "footer" in lowered:
        return "shared footer component"
    if "cookie" in lowered or "consent" in lowered:
        return "shared consent component"
    return None


def accessibility_findings(
    page_url: str,
    response: dict,
    screenshot_path: str | None,
    max_nodes_per_rule: int = 30,
) -> tuple[list[dict], dict]:
    findings = []
    violations = response.get("violations", []) if isinstance(response, dict) else []
    omitted_nodes = 0
    for violation in violations:
        tags = [str(tag) for tag in violation.get("tags", [])]
        criteria, level = wcag_metadata(tags)
        rule_id = str(violation.get("id", "unknown-rule"))
        impact = str(violation.get("impact") or "minor")
        help_text = str(violation.get("help") or violation.get("description") or rule_id)
        nodes = violation.get("nodes", [])
        omitted_nodes += max(0, len(nodes) - max_nodes_per_rule)
        for node in nodes[:max_nodes_per_rule]:
            targets = node.get("target", [])
            selector = " ".join(
                " ".join(item) if isinstance(item, list) else str(item)
                for item in targets
            ).strip() or "Element selector unavailable"
            failure = re.sub(
                r"^\s*Fix (?:any|all) of the following:\s*",
                "",
                str(node.get("failureSummary") or ""),
                flags=re.IGNORECASE,
            ).strip()
            recommended_fix = failure or (
                f"Review the affected element and follow the axe-core guidance for {rule_id}."
            )
            plain_problem = PLAIN_LANGUAGE_PROBLEMS.get(
                rule_id,
                f"This page element does not meet the “{help_text}” accessibility rule.",
            )
            plain_fix = PLAIN_LANGUAGE_FIXES.get(
                rule_id,
                f"Review this element and apply the axe-core guidance for “{help_text}”.",
            )
            criteria_text = ", ".join(criteria) if criteria else "Best practice"
            detail = (
                f"{help_text}. WCAG: {criteria_text}; {level}. "
                f"Affected element: {selector}. {recommended_fix}"
            )
            findings.append(
                {
                    "page_url": page_url,
                    "severity": IMPACT_SEVERITY.get(impact, "low"),
                    "category": "accessibility",
                    "title": f"Accessibility: {help_text}",
                    "detail": detail[:1200],
                    "metadata": {
                        "engine": "axe-core",
                        "axe_rule_id": rule_id,
                        "axe_impact": impact,
                        "wcag_criteria": criteria,
                        "wcag_level": level,
                        "affected_element": selector,
                        "dom_evidence": str(node.get("html") or "")[:1000],
                        "failure_summary": str(node.get("failureSummary") or "")[:1000],
                        "help_url": violation.get("helpUrl"),
                        "screenshot_path": screenshot_path,
                        "component_hint": component_hint(selector),
                        "why_it_matters": PLAIN_LANGUAGE_IMPACTS.get(
                            rule_id,
                            f"People using assistive technology may be unable to use or understand this element: {help_text.lower()}.",
                        ),
                        "plain_problem": plain_problem,
                        "plain_fix": plain_fix,
                        "what_happened": plain_problem,
                        "recommended_action": plain_fix,
                        "verification": (
                            f"Detected automatically by axe-core rule {rule_id} on the rendered DOM. "
                            "Automated accessibility checks do not replace manual testing."
                        ),
                    },
                }
            )
    return findings, {
        "engine": "axe-core",
        "violation_count": len(violations),
        "affected_element_count": len(findings),
        "omitted_element_count": omitted_nodes,
    }


async def capture_element_evidence(
    page: object,
    findings: list[dict],
    screenshot_dir: Path,
    filename_prefix: str,
    max_captures: int = 20,
) -> None:
    """Attach a human-readable location and a small visual crop to axe findings."""
    captured = 0
    for index, finding in enumerate(findings, start=1):
        metadata = finding.get("metadata") or {}
        selector = metadata.get("affected_element")
        if not selector or selector == "Element selector unavailable":
            continue
        try:
            locator = page.locator(selector).first
            if await locator.count() < 1:
                continue
            description = await locator.evaluate(
                """(element) => {
                    const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
                    const text = clean(element.innerText || element.textContent).slice(0, 80);
                    const name = clean(
                        element.getAttribute('aria-label') ||
                        element.getAttribute('title') ||
                        element.getAttribute('placeholder') ||
                        text
                    ).slice(0, 80);
                    const tag = element.tagName.toLowerCase();
                    const type = clean(element.getAttribute('type'));
                    const role = clean(element.getAttribute('role'));
                    const kind = role || (tag === 'input' && type ? `${type} input` : tag);
                    const section = element.closest(
                        '[data-framer-name], section, article, form, header, nav, main, footer'
                    );
                    let sectionName = '';
                    if (section) {
                        const heading = section.querySelector('h1, h2, h3, h4, h5, h6');
                        sectionName = clean(
                            section.getAttribute('data-framer-name') ||
                            section.getAttribute('aria-label') ||
                            (heading && heading.textContent) ||
                            section.id
                        ).slice(0, 100);
                        if (!sectionName) sectionName = section.tagName.toLowerCase();
                    }
                    return {
                        elementLabel: name
                            ? `${kind.charAt(0).toUpperCase()}${kind.slice(1)} “${name}”`
                            : `Unnamed ${kind}`,
                        pageSection: sectionName ? `${sectionName} section` : 'Page area',
                    };
                }"""
            )
            metadata["element_label"] = description.get("elementLabel")
            metadata["page_section"] = description.get("pageSection")
            box = await locator.bounding_box()
            if box:
                metadata["bounding_box"] = {
                    key: round(float(box[key]), 1)
                    for key in ("x", "y", "width", "height")
                }
            if captured < max_captures and await locator.is_visible():
                filename = f"{filename_prefix}-a11y-{index}.png"
                await locator.screenshot(path=str(screenshot_dir / filename))
                metadata["element_screenshot_path"] = filename
                captured += 1
        except Exception:
            # Some axe selectors cross frames or shadow roots and cannot be
            # replayed as a normal Playwright locator. The selector and DOM
            # evidence remain available in that case.
            continue


async def run_accessibility_scan(
    page: object,
    page_url: str,
    axe_source: str,
    screenshot_path: str | None,
    screenshot_dir: Path | None = None,
    filename_prefix: str | None = None,
) -> tuple[list[dict], dict]:
    await page.evaluate(axe_source)
    response = await page.evaluate(
        """async (options) => {
            const results = await axe.run(document, options);
            return { violations: results.violations };
        }""",
        AXE_OPTIONS,
    )
    findings, summary = accessibility_findings(page_url, response, screenshot_path)
    if screenshot_dir and filename_prefix:
        await capture_element_evidence(
            page,
            findings,
            screenshot_dir,
            filename_prefix,
        )
        summary["element_screenshot_count"] = sum(
            bool(finding.get("metadata", {}).get("element_screenshot_path"))
            for finding in findings
        )
    return findings, summary
