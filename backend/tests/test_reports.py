import io
import unittest
import zipfile

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
        "summary": {"health_score": 72, "pages_scanned": 10, "actionable_failed_requests": 1},
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
        self.assertNotIn(b"Severity | Page importance", payload)
        self.assertTrue(payload.endswith(b"%%EOF"))

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

    def test_public_html_is_branded_read_only_and_not_indexed(self) -> None:
        document = build_html(sample_scan(), "executive")

        self.assertIn("Quality Agency", document)
        self.assertIn("#123456", document)
        self.assertIn('name="robots" content="noindex,nofollow"', document)
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
