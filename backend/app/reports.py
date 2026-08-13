import csv
import html
import io
import textwrap
import zipfile
from datetime import datetime
from xml.sax.saxutils import escape


REPORT_KINDS = {"executive", "qa", "developer"}


def _accessibility_standard(finding: dict) -> str:
    if finding.get("category") != "accessibility":
        return ""
    criteria = finding.get("wcag_criteria") or []
    standard = f"WCAG {', '.join(criteria)}" if criteria else "Best practice"
    return f"{finding.get('axe_rule_id', 'axe-core rule')} | {standard} | {finding.get('wcag_level', '')}".strip(" |")


def report_table(scan: dict, kind: str, comparison: dict | None = None) -> tuple[list[str], list[list[object]]]:
    change_by_fingerprint = {
        item["fingerprint"]: item["change_status"]
        for item in (comparison or {}).get("items", [])
    }
    if kind == "executive":
        groups = comparison["items"] if comparison and comparison.get("baseline") else scan.get("issue_groups", [])
        headers = ["Severity", "Page importance", "Root cause", "Affected pages", "Suggested owner", "Recommended action"]
        rows = [
            [
                group["severity"],
                group.get("page_priority", "standard"),
                group["title"],
                len(group["affected_pages"]),
                group["owner"],
                group["recommended_action"],
            ]
            for group in groups
        ]
    elif kind == "qa":
        headers = ["Severity", "Page importance", "Category", "Finding", "Standard / rule", "Affected element", "Page", "Why it matters", "Verification"]
        rows = [
            [
                finding["severity"],
                finding.get("page_priority", "standard"),
                finding["category"],
                finding["title"],
                _accessibility_standard(finding),
                finding.get("affected_element", ""),
                finding.get("page_url", ""),
                finding.get("why_it_matters", ""),
                finding.get("verification", ""),
            ]
            for finding in scan.get("findings", [])
            if finding["severity"] != "info"
        ]
    else:
        headers = ["Severity", "Page importance", "Category", "Finding", "Standard / rule", "Affected element", "Page", "Technical evidence", "DOM evidence", "Screenshot evidence", "Recommended action"]
        rows = [
            [
                finding["severity"],
                finding.get("page_priority", "standard"),
                finding["category"],
                finding["title"],
                _accessibility_standard(finding),
                finding.get("affected_element", ""),
                finding.get("page_url", ""),
                finding["detail"],
                finding.get("dom_evidence", ""),
                finding.get("screenshot_path", ""),
                finding.get("recommended_action", ""),
            ]
            for finding in scan.get("findings", [])
        ]
    if comparison and comparison.get("baseline"):
        headers.insert(0, "Change")
        source = (
            [item.get("change_status", "") for item in comparison["items"]]
            if kind == "executive"
            else [change_by_fingerprint.get(finding.get("fingerprint", ""), "") for finding in scan.get("findings", []) if kind == "developer" or finding["severity"] != "info"]
        )
        rows = [[source[index] if index < len(source) else "", *row] for index, row in enumerate(rows)]
    return headers, rows


def report_filename(scan: dict, kind: str, extension: str) -> str:
    host = scan["url"].split("://", 1)[-1].split("/", 1)[0].replace(":", "-")
    date = scan["created_at"][:10]
    return f"bugbuster-{kind}-{host}-{date}.{extension}"


def build_csv(scan: dict, kind: str, comparison: dict | None = None) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    headers, rows = report_table(scan, kind, comparison)
    writer.writerow(headers)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def _excel_column(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def build_xlsx(scan: dict, kind: str, comparison: dict | None = None) -> bytes:
    headers, rows = report_table(scan, kind, comparison)
    all_rows = [headers, *rows]
    sheet_rows = []
    for row_index, row in enumerate(all_rows, 1):
        cells = []
        for column_index, value in enumerate(row, 1):
            ref = f"{_excel_column(column_index)}{row_index}"
            style = ' s="1"' if row_index == 1 else ""
            cells.append(f'<c r="{ref}" t="inlineStr"{style}><is><t>{escape(str(value))}</t></is></c>')
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    sheet = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
<sheetData>{"".join(sheet_rows)}</sheetData><autoFilter ref="A1:{_excel_column(len(headers))}{max(1, len(all_rows))}"/>
</worksheet>"""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>""",
        )
        archive.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""",
        )
        archive.writestr(
            "xl/workbook.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="BugBuster report" sheetId="1" r:id="rId1"/></sheets>
</workbook>""",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>""",
        )
        archive.writestr(
            "xl/styles.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="2"><font/><font><b/><color rgb="FFFFFFFF"/></font></fonts>
<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF187249"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs>
<cellXfs count="2"><xf/><xf fontId="1" fillId="2" applyFont="1" applyFill="1"/></cellXfs>
</styleSheet>""",
        )
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return output.getvalue()


def _pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("latin-1", "replace").decode("latin-1")


def _pdf_text_lines(value: object, width: int = 92) -> list[str]:
    text = " ".join(str(value or "").split())
    return textwrap.wrap(text, width=width, break_long_words=True, break_on_hyphens=False) or ["Not provided"]


def _pdf_field(label: str, value: object) -> list[dict]:
    return [
        {"text": label.upper(), "font": "F2", "size": 7, "leading": 9, "color": "muted", "gap": 4},
        *[
            {"text": line, "font": "F1", "size": 9, "leading": 11, "color": "body", "gap": 0}
            for line in _pdf_text_lines(value)
        ],
    ]


def _pdf_compact_field(label: str, value: object, width: int = 140, link: str | None = None) -> list[dict]:
    """Render complete appendix evidence without repeating a large field heading."""
    lines = _pdf_text_lines(value, width=width)
    return [
        {
            "text": f"{label.upper()}: {line}" if index == 0 else f"    {line}",
            "font": "F2" if index == 0 else "F1",
            "size": 7,
            "leading": 8,
            "color": "brand" if link else "body",
            "gap": 0,
            **({"link": link} if link else {}),
        }
        for index, line in enumerate(lines)
    ]


def _pdf_url_list_field(label: str, urls: list[str], remaining: int = 0) -> list[dict]:
    lines: list[dict] = [
        {"text": label.upper(), "font": "F2", "size": 7, "leading": 9, "color": "muted", "gap": 4}
    ]
    for url in urls:
        lines.extend(
            {
                "text": wrapped,
                "font": "F1",
                "size": 8,
                "leading": 10,
                "color": "brand",
                "gap": 0,
                "link": url,
            }
            for wrapped in _pdf_text_lines(url, width=105)
        )
    if remaining:
        lines.append({
            "text": f"Complete list in the occurrence index ({remaining} more pages)",
            "font": "F1", "size": 8, "leading": 10, "color": "muted", "gap": 1,
        })
    return lines


def _pdf_group_blocks(scan: dict, kind: str, comparison: dict | None) -> tuple[list[list[dict]], dict[str, int]]:
    groups = comparison["items"] if comparison and comparison.get("baseline") else scan.get("issue_groups", [])
    findings_by_fingerprint: dict[str, list[dict]] = {}
    for finding in scan.get("findings", []):
        findings_by_fingerprint.setdefault(str(finding.get("fingerprint") or ""), []).append(finding)
    references: dict[str, int] = {}
    blocks: list[list[dict]] = []
    for index, group in enumerate(groups[:1000], 1):
        fingerprint = group.get("fingerprint") or group.get("group_id")
        if fingerprint:
            references[fingerprint] = index
        pages = group.get("affected_pages", [])
        status = group.get("change_status")
        summary_parts = [
            group.get("severity", "unknown").upper(),
            f"{group.get('page_priority', 'standard').replace('_', ' ').title()} importance",
            f"{group.get('count', len(pages))} occurrences",
            f"{len(pages)} affected {'page' if len(pages) == 1 else 'pages'}",
        ]
        if status:
            summary_parts.insert(0, status.upper())
        block = [
            {"text": f"ISSUE GROUP {index}", "font": "F2", "size": 7, "leading": 9, "color": "brand", "gap": 10},
            {"text": group.get("title", "Untitled issue"), "font": "F2", "size": 11, "leading": 13, "color": "body", "gap": 1},
            {"text": "  -  ".join(summary_parts), "font": "F1", "size": 7.5, "leading": 10, "color": "muted", "gap": 2},
            *_pdf_field("What happened" if kind == "qa" else "Technical pattern", group.get("what_happened") or group.get("sample_detail")),
            *_pdf_field("Why it matters", group.get("why_it_matters")),
            *_pdf_field("Suggested owner", group.get("owner")),
            *_pdf_field("Recommended action", group.get("recommended_action")),
        ]
        if kind == "qa":
            block.extend(_pdf_field("How it was verified", group.get("verification")))
        if group.get("category") == "accessibility":
            sample_findings = findings_by_fingerprint.get(str(fingerprint or ""), []) or [
                item
                for item in scan.get("findings", [])
                if item.get("title") == group.get("title") and item.get("category") == group.get("category")
            ]
            sample_screenshot = group.get("example_element_screenshot_path") or next(
                (item.get("element_screenshot_path") or item.get("screenshot_path") for item in sample_findings if item.get("element_screenshot_path") or item.get("screenshot_path")),
                None,
            )
            block.extend(_pdf_field("WCAG / axe-core rule", _accessibility_standard(group)))
            block.extend(_pdf_field("Example affected element", group.get("example_affected_element")))
            if kind == "developer":
                block.extend(_pdf_field("Example DOM evidence", group.get("example_dom_evidence")))
                block.extend(_pdf_field("Example screenshot", sample_screenshot))
        if group.get("shared_origin"):
            origin = group["shared_origin"]
            block.extend(_pdf_field(
                "Likely shared origin",
                f"{origin['label']} ({origin['confidence']} confidence; {origin['affected_page_count']} pages)",
            ))
        if pages:
            block.extend(_pdf_url_list_field("Affected-page preview", pages[:3], max(0, len(pages) - 3)))
        block.append({"divider": True, "leading": 7, "gap": 4})
        blocks.append(block)
    return blocks, references


def _pdf_occurrence_blocks(scan: dict, kind: str, group_references: dict[str, int], comparison: dict | None) -> list[list[dict]]:
    findings = [
        item
        for item in scan.get("findings", [])
        if kind == "developer" or item.get("severity") != "info"
    ]
    groups_by_fingerprint = {
        (item.get("fingerprint") or item.get("group_id")): item
        for item in scan.get("issue_groups", [])
    }
    change_by_fingerprint = {
        item["fingerprint"]: item["change_status"]
        for item in (comparison or {}).get("items", [])
        if item.get("fingerprint")
    }
    blocks: list[list[dict]] = []
    for index, finding in enumerate(findings[:1000], 1):
        fingerprint = finding.get("fingerprint", "")
        group = groups_by_fingerprint.get(fingerprint, {})
        group_number = group_references.get(fingerprint)
        change = change_by_fingerprint.get(fingerprint)
        summary_parts = [
            finding.get("severity", "unknown").upper(),
            finding.get("page_priority", "standard").replace("_", " ").title(),
            finding.get("category", "other").title(),
        ]
        if group_number:
            summary_parts.insert(0, f"Group {group_number}")
        if change:
            summary_parts.insert(0, change.upper())
        occurrence_heading = (
            f"OCCURRENCE {index}  |  {'  |  '.join(summary_parts)}  |  "
            f"{finding.get('title', 'Untitled finding')}"
        )
        block = [
            *[
                {
                    "text": line,
                    "font": "F2" if line_index == 0 else "F1",
                    "size": 7.5,
                    "leading": 9,
                    "color": "brand" if line_index == 0 else "muted",
                    "gap": 4 if line_index == 0 else 0,
                }
                for line_index, line in enumerate(_pdf_text_lines(occurrence_heading, width=138))
            ],
            *_pdf_compact_field("Page", finding.get("page_url"), link=finding.get("page_url")),
            *_pdf_compact_field("Evidence", finding.get("detail")),
        ]
        if finding.get("category") == "accessibility":
            block.extend(_pdf_compact_field("WCAG / rule", _accessibility_standard(finding)))
            block.extend(_pdf_compact_field("Affected element", finding.get("affected_element")))
            if kind == "developer":
                block.extend(_pdf_compact_field("DOM", finding.get("dom_evidence")))
                block.extend(_pdf_compact_field("Screenshot", finding.get("screenshot_path")))
        # Common guidance is printed once in the root-cause card. Preserve any
        # occurrence-specific value here when it differs from the grouped value.
        distinct_fields = [
            ("Impact", "why_it_matters"),
            ("Verification", "verification"),
            ("Action", "recommended_action"),
        ]
        for label, key in distinct_fields:
            value = finding.get(key)
            if value and value != group.get(key):
                block.extend(_pdf_compact_field(label, value))
        block.append({"divider": True, "leading": 3.5, "gap": 2})
        blocks.append(block)
    return blocks


def _pdf_issue_blocks(scan: dict, kind: str, comparison: dict | None) -> list[list[dict]]:
    blocks: list[list[dict]] = []
    if kind == "executive":
        groups = comparison["items"] if comparison and comparison.get("baseline") else scan.get("issue_groups", [])
        for index, group in enumerate(groups[:1000], 1):
            pages = group.get("affected_pages", [])
            status = group.get("change_status")
            summary = (
                f"{group.get('severity', 'unknown').upper()} severity  -  "
                f"{group.get('page_priority', 'standard').replace('_', ' ').title()} page importance  -  "
                f"{len(pages)} affected {'page' if len(pages) == 1 else 'pages'}"
            )
            if status:
                summary = f"{status.upper()}  -  {summary}"
            blocks.append(
                [
                    {"text": f"ROOT CAUSE {index}", "font": "F2", "size": 7, "leading": 9, "color": "brand", "gap": 12},
                    {"text": group.get("title", "Untitled issue"), "font": "F2", "size": 12, "leading": 15, "color": "body", "gap": 2},
                    {"text": summary, "font": "F1", "size": 8, "leading": 11, "color": "muted", "gap": 2},
                    *_pdf_field("What happened", group.get("what_happened") or group.get("sample_detail")),
                    *_pdf_field("Why it matters", group.get("why_it_matters")),
                    *_pdf_field("Suggested owner", group.get("owner")),
                    *_pdf_field("Recommended action", group.get("recommended_action")),
                    *(
                        _pdf_field(
                            "Likely shared origin",
                            f"{group['shared_origin']['label']} ({group['shared_origin']['confidence']} confidence)",
                        )
                        if group.get("shared_origin")
                        else []
                    ),
                    *_pdf_url_list_field("Affected pages", pages[:12], max(0, len(pages) - 12)),
                    {"divider": True, "leading": 9, "gap": 6},
                ]
            )
    else:
        group_blocks, _ = _pdf_group_blocks(scan, kind, comparison)
        blocks.extend(group_blocks)
        blocks.append([
            {"text": "COMPLETE EVIDENCE EXPORT", "font": "F2", "size": 10, "leading": 13, "color": "body", "gap": 14},
            {"text": "This PDF is intentionally organized around actionable root causes. Download the matching CSV or Excel report for every occurrence, affected URL, and full row-level evidence without making this document unnecessarily long.", "font": "F1", "size": 8, "leading": 11, "color": "muted", "gap": 6},
        ])
    return blocks


def build_pdf(scan: dict, kind: str, comparison: dict | None = None) -> bytes:
    title = scan.get("report_title") or f"{kind.title()} website report"
    agency = scan.get("agency_name") or "BugBuster Website Explorer"
    summary = scan.get("summary", {})
    options = scan.get("scan_options") or {}
    health_value = summary.get("health_score")
    health_label = f"{health_value}/100" if health_value is not None else "Not calculated"
    summary_parts = [
        f"Health score: {health_label}",
        f"Pages scanned: {summary.get('pages_scanned', 0)}",
        f"Root causes: {len(scan.get('issue_groups', []))}",
    ]
    if not options or options.get("network", False):
        summary_parts.append(
            "Actionable request failures: "
            f"{summary.get('actionable_failed_requests', summary.get('failed_requests', 0))}"
        )
    health_categories = summary.get("health_categories") or {}
    checked_categories = [
        f"{category.get('label', key.title())}: {category.get('score')}/100"
        for key, category in health_categories.items()
        if category.get("checked") and category.get("score") is not None
    ]
    health_coverage = summary.get("health_coverage") or {}
    intro = [
        {"text": agency, "font": "F2", "size": 9, "leading": 12, "color": "brand", "gap": 0},
        {"text": title, "font": "F2", "size": 20, "leading": 24, "color": "body", "gap": 5},
        {"text": scan["url"], "font": "F1", "size": 9, "leading": 12, "color": "brand", "gap": 1, "link": scan["url"]},
        {"text": f"Scan completed: {scan['created_at']}", "font": "F1", "size": 8, "leading": 11, "color": "muted", "gap": 0},
        {"divider": True, "leading": 12, "gap": 9},
        {"text": "SCAN SUMMARY", "font": "F2", "size": 8, "leading": 11, "color": "brand", "gap": 2},
        {
            "text": "    ".join(summary_parts),
            "font": "F2",
            "size": 10,
            "leading": 14,
            "color": "body",
            "gap": 2,
        },
    ]
    if health_coverage:
        intro.append({
            "text": (
                f"Score coverage: {health_coverage.get('scope_percent', 0)}%"
                f"  -  {str(health_coverage.get('confidence', 'focused')).replace('_', ' ').title()}"
            ),
            "font": "F1", "size": 9, "leading": 12, "color": "muted", "gap": 1,
        })
    for offset in range(0, len(checked_categories), 3):
        intro.append({
            "text": "    ".join(checked_categories[offset:offset + 3]),
            "font": "F1", "size": 9, "leading": 12, "color": "body", "gap": 1,
        })
    blocks = [intro]
    if comparison and comparison.get("baseline"):
        counts = comparison["counts"]
        score_comparison = comparison.get("score") or {}
        blocks.append(
            [
                {"text": "SCAN COMPARISON", "font": "F2", "size": 8, "leading": 11, "color": "brand", "gap": 12},
                {"text": f"Compared with scan from {comparison['baseline']['created_at']}", "font": "F1", "size": 9, "leading": 12, "color": "muted", "gap": 1},
                {
                    "text": f"New: {counts['new']}    Fixed: {counts['fixed']}    Recurring: {counts['recurring']}    Unchanged: {counts['unchanged']}",
                    "font": "F2",
                    "size": 10,
                    "leading": 14,
                    "color": "body",
                    "gap": 2,
                },
                {
                    "text": (
                        f"Health score change: {score_comparison.get('change', 0):+g} points"
                        if score_comparison.get("compatible")
                        else score_comparison.get("reason", "Health-score comparison unavailable.")
                    ),
                    "font": "F1", "size": 8, "leading": 11, "color": "muted", "gap": 1,
                },
            ]
        )
    if kind != "executive":
        blocks.append([
            {"text": "HOW TO READ THIS REPORT", "font": "F2", "size": 8, "leading": 11, "color": "brand", "gap": 12},
            {"text": "Start with Prioritized issue groups. Each group explains one problem, its impact, owner, and recommended fix without repeating the same guidance for every page.", "font": "F1", "size": 8, "leading": 11, "color": "body", "gap": 1},
            {"text": "Each group includes representative evidence and an affected-page preview. Green website links are clickable. Use CSV or Excel when you need the complete occurrence ledger.", "font": "F1", "size": 8, "leading": 11, "color": "muted", "gap": 2},
        ])
    blocks.append(
        [
            {
                "text": "PRIORITIZED ROOT CAUSES" if kind == "executive" else "PRIORITIZED ISSUE GROUPS",
                "font": "F2",
                "size": 14,
                "leading": 18,
                "color": "body",
                "gap": 18,
            }
        ]
    )
    issue_blocks = _pdf_issue_blocks(scan, kind, comparison)
    blocks.extend(issue_blocks or [[{"text": "No findings were recorded for this report.", "font": "F1", "size": 10, "leading": 14, "color": "muted", "gap": 8}]])

    pages: list[list[dict]] = [[]]
    remaining_height = 682
    for block in blocks:
        block_height = sum(item.get("leading", 11) + item.get("gap", 0) for item in block)
        if pages[-1] and block_height > remaining_height:
            pages.append([])
            remaining_height = 682
        # Very long evidence (for example DOM snippets) can exceed a page by
        # itself. Split it safely so complete evidence is never drawn below the
        # footer or silently lost.
        for item in block:
            item_height = item.get("leading", 11) + item.get("gap", 0)
            if pages[-1] and item_height > remaining_height:
                pages.append([])
                remaining_height = 682
            pages[-1].append(item)
            remaining_height -= item_height

    brand = scan.get("brand_color") or "#187249"
    try:
        brand_rgb = tuple(int(brand[index:index + 2], 16) / 255 for index in (1, 3, 5))
    except (TypeError, ValueError):
        brand_rgb = (0.094, 0.447, 0.286)
    colors = {
        "brand": brand_rgb,
        "body": (0.09, 0.21, 0.16),
        "muted": (0.36, 0.45, 0.41),
    }
    objects: list[bytes] = [
        b"",
        b"",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
    ]
    page_ids = []
    for page_number, page_lines in enumerate(pages, 1):
        page_id = len(objects) + 1
        content_id = page_id + 1
        page_ids.append(page_id)
        link_rectangles: list[tuple[float, float, float, float, str]] = []
        content_lines = [
            f"{brand_rgb[0]:.3f} {brand_rgb[1]:.3f} {brand_rgb[2]:.3f} rg",
            "42 770 528 4 re f",
        ]
        y = 748
        if page_number > 1:
            content_lines.extend(
                [
                    "BT /F2 8 Tf",
                    f"{brand_rgb[0]:.3f} {brand_rgb[1]:.3f} {brand_rgb[2]:.3f} rg",
                    f"42 748 Td ({_pdf_escape(title + ' - continued')}) Tj ET",
                ]
            )
            y = 724
        for line in page_lines:
            y -= line.get("gap", 0)
            if line.get("divider"):
                content_lines.extend(["0.84 0.89 0.86 RG", f"42 {y:.1f} m 570 {y:.1f} l S"])
                y -= line.get("leading", 9)
                continue
            red, green, blue = colors[line.get("color", "body")]
            text = str(line.get("text", ""))
            size = float(line.get("size", 9))
            content_lines.extend(
                [
                    f"BT /{line.get('font', 'F1')} {size:g} Tf",
                    f"{red:.3f} {green:.3f} {blue:.3f} rg",
                    f"42 {y:.1f} Td ({_pdf_escape(text)}) Tj ET",
                ]
            )
            if line.get("link"):
                estimated_width = min(528.0, max(18.0, len(text) * size * 0.52))
                link_rectangles.append((42.0, y - 2.0, 42.0 + estimated_width, y + size + 2.0, str(line["link"])))
            y -= line.get("leading", 11)
        content_lines.extend(
            [
                "BT /F1 8 Tf 0.36 0.45 0.41 rg",
                f"42 28 Td (Read-only BugBuster report) Tj ET",
                f"BT /F1 8 Tf 0.36 0.45 0.41 rg 535 28 Td (Page {page_number} of {len(pages)}) Tj ET",
            ]
        )
        content = "\n".join(content_lines).encode("latin-1")
        annotation_ids = list(range(content_id + 1, content_id + 1 + len(link_rectangles)))
        annotations = f" /Annots [{' '.join(f'{item} 0 R' for item in annotation_ids)}]" if annotation_ids else ""
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {content_id} 0 R{annotations} >>".encode())
        objects.append(b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream")
        for left, bottom, right, top, url in link_rectangles:
            objects.append(
                (
                    f"<< /Type /Annot /Subtype /Link /Rect [{left:.1f} {bottom:.1f} {right:.1f} {top:.1f}] "
                    f"/Border [0 0 0] /A << /S /URI /URI ({_pdf_escape(url)}) >> >>"
                ).encode("latin-1")
            )
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(f'{page_id} 0 R' for page_id in page_ids)}] /Count {len(page_ids)} >>".encode()
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for object_id, body in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{object_id} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return bytes(output)


def build_html(scan: dict, kind: str, comparison: dict | None = None) -> str:
    headers, rows = report_table(scan, kind, comparison)
    brand = scan.get("brand_color") or "#187249"
    agency = html.escape(scan.get("agency_name") or "BugBuster Website Explorer")
    title = html.escape(scan.get("report_title") or f"{kind.title()} website report")
    summary = scan.get("summary", {})
    options = scan.get("scan_options") or {}
    health_value = summary.get("health_score")
    health_label = str(health_value) if health_value is not None else "—"
    metrics = [
        (health_label, "Health score" if health_value is not None else "Health score not calculated"),
        (summary.get("pages_scanned", 0), "Pages scanned"),
        (len(scan.get("issue_groups", [])), "Root causes"),
    ]
    if not options or options.get("network", False):
        metrics.append((
            summary.get("actionable_failed_requests", summary.get("failed_requests", 0)),
            "Request failures",
        ))
    metrics_html = "".join(
        f"<b>{html.escape(str(value))}<small>{html.escape(label)}</small></b>"
        for value, label in metrics
    )
    health_categories = summary.get("health_categories") or {}
    category_html = "".join(
        f"<div class=\"health-category\"><span>{html.escape(category.get('label', key.title()))}</span>"
        f"<b>{html.escape(str(category.get('score')))}<small>/100</small></b></div>"
        for key, category in health_categories.items()
        if category.get("checked") and category.get("score") is not None
    )
    health_coverage = summary.get("health_coverage") or {}
    health_details_html = ""
    if category_html:
        health_details_html = f"""<section><h2>BugBuster health breakdown</h2>
<p>{html.escape(str(health_coverage.get('scope_percent', 0)))}% score coverage · {html.escape(str(health_coverage.get('confidence', 'focused')).replace('_', ' ').title())}</p>
<div class="health-categories">{category_html}</div></section>"""
    comparison_html = ""
    if comparison and comparison.get("baseline"):
        counts = comparison["counts"]
        score_comparison = comparison.get("score") or {}
        score_comparison_text = (
            f"Health score changed by {score_comparison.get('change', 0):+g} points using matching settings."
            if score_comparison.get("compatible")
            else score_comparison.get("reason", "Health-score comparison unavailable.")
        )
        comparison_html = f"""<section><h2>Changes since the previous scan</h2><div class="metrics">
<b>{counts['new']}<small>New</small></b><b>{counts['fixed']}<small>Fixed</small></b>
<b>{counts['recurring']}<small>Recurring</small></b><b>{counts['unchanged']}<small>Unchanged</small></b></div>
<p>{html.escape(score_comparison_text)}</p></section>"""
    table_header = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
    table_rows = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(value))}</td>" for value in row) + "</tr>"
        for row in rows
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="robots" content="noindex,nofollow">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><style>
:root{{--brand:{brand}}}body{{font:14px system-ui;color:#17352a;margin:0;background:#f5f8f6}}main{{max-width:1120px;margin:32px auto;padding:28px;background:white;border-radius:16px}}
header{{border-bottom:4px solid var(--brand);padding-bottom:18px}}h1{{margin:5px 0}}p,small{{color:#60766b}}.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}
.metrics b{{padding:16px;background:#f0f7f3;border-radius:10px;font-size:26px}}.metrics small{{display:block;font-size:11px;text-transform:uppercase}}
.health-categories{{display:grid;grid-template-columns:repeat(3,1fr);gap:9px}}.health-category{{display:flex;justify-content:space-between;align-items:center;padding:13px;border:1px solid #dce7e0;border-radius:10px;background:#f7fbf8}}
.health-category span{{font-size:12px;font-weight:700}}.health-category b{{font-size:20px;color:var(--brand)}}.health-category b small{{display:inline;font-size:9px}}
table{{width:100%;border-collapse:collapse;margin-top:14px;font-size:12px}}th{{background:var(--brand);color:white;text-align:left}}th,td{{padding:9px;border:1px solid #dce7e0;vertical-align:top}}
@media(max-width:700px){{main{{margin:0;border-radius:0;padding:16px}}.metrics{{grid-template-columns:repeat(2,1fr)}}.health-categories{{grid-template-columns:1fr}}table{{display:block;overflow:auto}}}}</style></head>
<body><main><header><small>{agency}</small><h1>{title}</h1><p>{html.escape(scan['url'])} · {html.escape(scan['created_at'])}</p></header>
<section><h2>Scan summary</h2><div class="metrics">{metrics_html}</div></section>
{health_details_html}{comparison_html}<section><h2>{kind.title()} findings</h2><table><thead><tr>{table_header}</tr></thead><tbody>{table_rows}</tbody></table></section>
<p><small>Generated {datetime.now().astimezone().isoformat(timespec='seconds')} · Read-only BugBuster report</small></p></main></body></html>"""
