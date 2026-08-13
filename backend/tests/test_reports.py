import io
import csv
import re
import unittest
import zipfile

from app.insights import build_issue_groups
from app.reports import build_csv, build_html, build_pdf, build_xlsx


def sample_scan() -> dict:
    group = {
        "group_id": "abc",
        "fingerprint": "abc",
        "severity": "high",
        "page_priority": "critical",
        "title": "Page could not be loaded",
        "affected_pages": ["https://example.com/checkout"],
        "owner": "Developer",
        "recommended_action": "Restore the checkout route.",
    }
    finding = {
        "fingerprint": "abc",
        "severity": "high",
        "page_priority": "critical",
        "category": "page",
        "title": "Page could not be loaded",
        "page_url": "https://example.com/checkout",
        "detail": "The page returned status 500.",
        "why_it_matters": "Customers cannot purchase.",
        "verification": "HTTP 500 confirmed.",
        "recommended_action": "Restore the checkout route.",
    }
    return {
        "id": "scan-1",
        "url": "https://example.com/",
        "created_at": "2026-07-27T10:00:00+00:00",
        "agency_name": "Quality Agency",
        "report_title": "Release readiness",
        "brand_color": "#123456",
        "summary": {
            "health_score": 72,
            "pages_scanned": 10,
            "actionable_failed_requests": 1,
            "health_categories": {
                "reliability": {"label": "Reliability", "score": 54, "checked": True},
                "accessibility": {"label": "Accessibility", "score": None, "checked": False},
            },
            "health_coverage": {"scope_percent": 65, "confidence": "standard"},
        },
        "issue_groups": [group],
        "findings": [finding],
    }


class ReportExportTests(unittest.TestCase):
    def test_pdf_is_a_valid_pdf_payload_with_branding(self) -> None:
        payload = build_pdf(sample_scan(), "executive")

        self.assertTrue(payload.startswith(b"%PDF-1.4"))
        self.assertIn(b"Quality Agency", payload)
        self.assertIn(b"ROOT CAUSE 1", payload)
        self.assertIn(b"WHAT HAPPENED", payload)
        self.assertIn(b"RECOMMENDED ACTION", payload)
        self.assertIn(b"AFFECTED PAGES", payload)
        self.assertIn(b"Page 1 of", payload)
        self.assertIn(b"/Subtype /Link", payload)
        self.assertIn(b"/S /URI /URI (https://example.com/)", payload)
        self.assertIn(b"/S /URI /URI (https://example.com/checkout)", payload)
        self.assertNotIn(b"Severity | Page importance", payload)
        self.assertTrue(payload.endswith(b"%%EOF"))

    def test_qa_pdf_groups_repeated_guidance_without_repeating_every_occurrence(self) -> None:
        scan = sample_scan()
        scan["findings"] = [
            {
                **scan["findings"][0],
                "page_url": f"https://example.com/products/{index}",
                "detail": f"Unique evidence marker {index}: response took {3000 + index} ms.",
            }
            for index in range(60)
        ]
        scan["issue_groups"] = build_issue_groups(scan["findings"])

        payload = build_pdf(scan, "qa")
        page_count = max(int(value) for value in re.findall(rb"/Count (\d+)", payload))

        self.assertIn(b"PRIORITIZED ISSUE GROUPS", payload)
        self.assertIn(b"COMPLETE EVIDENCE EXPORT", payload)
        self.assertIn(b"CSV or Excel", payload)
        self.assertNotIn(b"OCCURRENCE 60", payload)
        self.assertLessEqual(page_count, 10)

    def test_developer_pdf_keeps_dom_and_screenshot_in_compact_index(self) -> None:
        scan = sample_scan()
        finding = {
            **scan["findings"][0],
            "category": "accessibility",
            "title": "Accessibility: Form elements must have labels",
            "axe_rule_id": "label",
            "wcag_criteria": ["1.3.1", "4.1.2"],
            "wcag_level": "Level A",
            "affected_element": "form input#email",
            "dom_evidence": '<input id="email">',
            "screenshot_path": "scan-desktop.png",
        }
        scan["findings"] = [finding]
        scan["issue_groups"] = build_issue_groups(scan["findings"])

        payload = build_pdf(scan, "developer")

        self.assertIn(b"EXAMPLE DOM EVIDENCE", payload)
        self.assertIn(b'<input id="email">', payload)
        self.assertIn(b"EXAMPLE SCREENSHOT", payload)
        self.assertIn(b"scan-desktop.png", payload)

    def test_csv_is_excel_compatible_and_contains_page_importance(self) -> None:
        payload = build_csv(sample_scan(), "qa")
        text = payload.decode("utf-8-sig")

        self.assertIn("Page importance", text)
        self.assertIn("critical", text)
        self.assertIn("checkout", text)

    def test_xlsx_contains_a_workbook_and_worksheet(self) -> None:
        payload = build_xlsx(sample_scan(), "developer")

        with zipfile.ZipFile(io.BytesIO(payload)) as workbook:
            self.assertIn("xl/workbook.xml", workbook.namelist())
            self.assertIn("xl/worksheets/sheet1.xml", workbook.namelist())
            self.assertIn(b"Technical evidence", workbook.read("xl/worksheets/sheet1.xml"))

    def test_accessibility_evidence_is_in_qa_and_developer_exports(self) -> None:
        scan = sample_scan()
        scan["findings"] = [
            {
                **scan["findings"][0],
                "category": "accessibility",
                "title": "Accessibility: Form elements must have labels",
                "axe_rule_id": "label",
                "wcag_criteria": ["1.3.1", "4.1.2"],
                "wcag_level": "Level A",
                "affected_element": "form input#email",
                "dom_evidence": '<input id="email">',
                "screenshot_path": "scan-desktop.png",
            }
        ]

        qa = build_csv(scan, "qa").decode("utf-8-sig")
        developer = build_csv(scan, "developer").decode("utf-8-sig")

        self.assertIn("WCAG 1.3.1, 4.1.2", qa)
        self.assertIn("form input#email", qa)
        developer_rows = list(csv.reader(io.StringIO(developer)))
        self.assertIn('<input id="email">', developer_rows[1])
        self.assertIn("scan-desktop.png", developer)

    def test_public_html_is_branded_read_only_and_not_indexed(self) -> None:
        document = build_html(sample_scan(), "executive")

        self.assertIn("Quality Agency", document)
        self.assertIn("#123456", document)
        self.assertIn('name="robots" content="noindex,nofollow"', document)
        self.assertIn("BugBuster health breakdown", document)
        self.assertIn("Reliability", document)
        self.assertIn("Read-only BugBuster report", document)

    def test_comparison_status_is_included_in_export(self) -> None:
        comparison = {
            "baseline": {"created_at": "2026-07-20T10:00:00+00:00"},
            "counts": {"new": 1, "fixed": 0, "recurring": 0, "unchanged": 0},
            "items": [{**sample_scan()["issue_groups"][0], "change_status": "new"}],
        }

        text = build_csv(sample_scan(), "executive", comparison).decode("utf-8-sig")

        self.assertIn("Change", text)
        self.assertIn("new", text)


if __name__ == "__main__":
    unittest.main()
