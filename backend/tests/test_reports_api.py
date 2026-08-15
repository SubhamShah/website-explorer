import tempfile
import unittest
from pathlib import Path

from app import store
from app.main import (
    PagePriorityRequest,
    ReportSettingsRequest,
    ShareReportRequest,
    download_report,
    report_comparison,
    share_report,
    shared_report,
    update_page_priority,
    update_report_settings,
    ScanRequest,
)


class FakeRequest:
    def url_for(self, _name: str, **parameters: str) -> str:
        return f"http://test/reports/shared/{parameters['token']}"


class ReportApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_db_path = store.DB_PATH
        self.temp_dir = tempfile.TemporaryDirectory()
        store.DB_PATH = Path(self.temp_dir.name) / "test-explorer.db"
        self.scan = store.create_scan("https://example.com", 2, 1)
        store.save_page(
            self.scan["id"],
            {
                "url": "https://example.com/checkout",
                "final_url": "https://example.com/checkout",
                "depth": 1,
                "status": 500,
                "title": "Checkout",
                "h1": "Checkout",
                "meta_description": "",
                "load_ms": 100,
                "screenshot_path": None,
                "error_type": None,
                "error_detail": None,
                "redirect_chain": [],
                "console": [],
                "network": [],
                "links": [],
            },
        )
        store.save_finding(
            self.scan["id"],
            {
                "page_url": "https://example.com/checkout",
                "severity": "high",
                "category": "page",
                "title": "Page could not be loaded",
                "detail": "The page returned status 500.",
            },
        )

    def tearDown(self) -> None:
        store.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_priority_branding_download_and_shared_report(self) -> None:
        priority = update_page_priority(
            self.scan["id"],
            PagePriorityRequest(page_url="https://example.com/checkout", priority="critical"),
        )
        branding = update_report_settings(
            self.scan["id"],
            ReportSettingsRequest(
                agency_name="Quality Agency",
                report_title="Release report",
                brand_color="#123456",
            ),
        )
        pdf = download_report(
            self.scan["id"],
            "pdf",
            kind="executive",
            compare_to=None,
        )
        shared = share_report(
            self.scan["id"],
            ShareReportRequest(report_kind="executive", expires_hours=24),
            FakeRequest(),
        )
        public = shared_report(shared["url"].rsplit("/", 1)[-1])

        self.assertEqual(priority["priority"], "critical")
        self.assertEqual(branding["agency_name"], "Quality Agency")
        self.assertEqual(pdf.media_type, "application/pdf")
        self.assertTrue(bytes(pdf.body).startswith(b"%PDF"))
        self.assertTrue(shared["read_only"])
        self.assertEqual(public.status_code, 200)
        self.assertIn(b"Quality Agency", public.body)
        self.assertIn(b"noindex,nofollow", public.body)

    def test_report_comparison_is_explicit_and_current_only_is_default(self) -> None:
        scan = {
            "comparison": {
                "baseline": {"id": "older"},
                "counts": {"new": 1, "fixed": 0, "recurring": 0, "unchanged": 0},
                "items": [],
            }
        }

        self.assertIsNone(report_comparison(scan, None))
        self.assertEqual(report_comparison(scan, "__previous__"), scan["comparison"])

    def test_nontechnical_scan_defaults_keep_advanced_checks_optional(self) -> None:
        request = ScanRequest(url="https://example.com", authorized=True)

        self.assertTrue(request.scan_options.page_health)
        self.assertTrue(request.scan_options.content_quality)
        self.assertTrue(request.scan_options.screenshots)
        self.assertFalse(request.scan_options.accessibility)
        self.assertFalse(request.scan_options.network)
        self.assertFalse(request.scan_options.console)
        self.assertFalse(request.scan_options.sitemap_indexing)
        self.assertFalse(request.scan_options.passive_security)

    def test_page_priority_change_recalculates_completed_health_score(self) -> None:
        store.update_scan(
            self.scan["id"],
            status="completed",
            summary={"pages_scanned": 1, "network_requests": 0, "actionable_failed_requests": 0},
        )
        result = update_page_priority(
            self.scan["id"],
            PagePriorityRequest(page_url="https://example.com/checkout", priority="critical"),
        )
        updated = store.get_scan(self.scan["id"])

        self.assertIsNotNone(result["health_score"])
        self.assertEqual(updated["summary"]["health_method_version"], "2.1")
        self.assertEqual(
            updated["summary"]["health_top_impacts"][0]["priority_multiplier"],
            3.0,
        )


if __name__ == "__main__":
    unittest.main()
