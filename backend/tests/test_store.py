import tempfile
import unittest
from pathlib import Path

from app import store


class DeleteScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_db_path = store.DB_PATH
        self.temp_dir = tempfile.TemporaryDirectory()
        store.DB_PATH = Path(self.temp_dir.name) / "test-explorer.db"

    def tearDown(self) -> None:
        store.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_delete_scan_removes_scan_pages_and_findings(self) -> None:
        scan = store.create_scan("https://example.com", 2, 1)
        store.save_page(
            scan["id"],
            {
                "url": "https://example.com",
                "final_url": "https://example.com",
                "depth": 0,
                "status": 200,
                "title": "Example",
                "h1": "Example",
                "meta_description": "Example page",
                "load_ms": 100,
                "screenshot_path": "scan-page.png",
                "error_type": None,
                "error_detail": None,
                "redirect_chain": [],
                "console": [],
                "network": [],
                "links": [],
                "responsive": {
                    "desktop": {"screenshot_path": "scan-page-desktop.png"},
                    "mobile": {"screenshot_path": "scan-page-mobile.png"},
                },
            },
        )
        store.save_finding(
            scan["id"],
            {"page_url": scan["url"], "severity": "low", "category": "seo", "title": "Test", "detail": "Test"},
        )

        deleted, screenshots = store.delete_scan(scan["id"])

        self.assertTrue(deleted)
        self.assertEqual(
            screenshots,
            ["scan-page-desktop.png", "scan-page-mobile.png", "scan-page.png"],
        )
        self.assertIsNone(store.get_scan(scan["id"]))
        with store.connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM findings").fetchone()[0], 0)

    def test_delete_missing_scan_returns_false(self) -> None:
        deleted, screenshots = store.delete_scan("missing")
        self.assertFalse(deleted)
        self.assertEqual(screenshots, [])

    def test_scan_details_attaches_pages_that_linked_to_finding_url(self) -> None:
        scan = store.create_scan("https://example.com", 3, 1)
        target = "https://example.com/missing"
        for url, links in [
            ("https://example.com/source", [target]),
            ("https://example.com/another-source", [target]),
            (target, [target]),
        ]:
            store.save_page(
                scan["id"],
                {
                    "url": url,
                    "final_url": url,
                    "depth": 1,
                    "status": 404 if url == target else 200,
                    "title": "",
                    "h1": "",
                    "meta_description": "",
                    "load_ms": 100,
                    "screenshot_path": None,
                    "error_type": None,
                    "error_detail": None,
                    "redirect_chain": [],
                    "console": [],
                    "network": [],
                    "links": links,
                },
            )
        store.save_finding(
            scan["id"],
            {"page_url": target, "severity": "high", "category": "page", "title": "Missing", "detail": "404"},
        )

        details = store.scan_details(scan["id"])

        self.assertEqual(
            details["findings"][0]["discovered_on"],
            ["https://example.com/another-source", "https://example.com/source"],
        )

    def test_overview_and_paginated_results_do_not_repeat_heavy_page_evidence(self) -> None:
        scan = store.create_scan("https://example.com", 3, 1)
        for index in range(3):
            url = f"https://example.com/page-{index}"
            store.save_page(
                scan["id"],
                {
                    "url": url,
                    "final_url": url,
                    "depth": 1,
                    "status": 200,
                    "title": f"Page {index}",
                    "h1": f"Page {index}",
                    "meta_description": "Description",
                    "load_ms": 100,
                    "screenshot_path": None,
                    "error_type": None,
                    "error_detail": None,
                    "redirect_chain": [],
                    "console": [{"level": "error", "message": "Heavy evidence"}],
                    "network": [{"url": "https://api.example.com", "status": 200}],
                    "links": [],
                    "responsive": {"desktop": {"width": 1440}},
                },
            )
            store.save_finding(
                scan["id"],
                {
                    "page_url": url,
                    "severity": "low",
                    "category": "seo",
                    "title": f"Finding {index}",
                    "detail": "Detail",
                },
            )

        overview = store.scan_overview(scan["id"])
        pages = store.page_summaries(scan["id"], offset=0, limit=2)
        findings = store.findings_page(scan["id"], offset=0, limit=2)
        matching_findings = store.findings_page(
            scan["id"], offset=0, limit=10, severity="low", query="finding 2"
        )
        page = store.page_details(scan["id"], pages["items"][0]["id"])

        self.assertNotIn("pages", overview)
        self.assertNotIn("findings", overview)
        self.assertEqual(overview["page_count"], 3)
        self.assertEqual(overview["finding_count"], 3)
        self.assertEqual(len(pages["items"]), 2)
        self.assertTrue(pages["has_more"])
        self.assertNotIn("network", pages["items"][0])
        self.assertEqual(pages["items"][0]["responsive_viewport_count"], 1)
        self.assertEqual(len(findings["items"]), 2)
        self.assertTrue(findings["has_more"])
        self.assertEqual(matching_findings["total"], 1)
        self.assertEqual(matching_findings["items"][0]["title"], "Finding 2")
        self.assertEqual(page["network"][0]["status"], 200)
        self.assertEqual(len(page["findings"]), 1)

    def test_scan_details_enriches_groups_and_compares_with_previous_scan(self) -> None:
        baseline = store.create_scan("https://example.com", 3, 1)
        store.save_finding(
            baseline["id"],
            {
                "page_url": "https://example.com/about",
                "severity": "medium",
                "category": "seo",
                "title": "Missing page title",
                "detail": "This page does not have a usable HTML title.",
            },
        )
        store.update_scan(
            baseline["id"],
            status="completed",
            completed_at="2026-07-27T10:00:00+00:00",
            summary={"health_score": 80},
        )
        current = store.create_scan("https://example.com", 3, 1)
        store.save_finding(
            current["id"],
            {
                "page_url": "https://example.com/contact",
                "severity": "low",
                "category": "seo",
                "title": "Missing H1 heading",
                "detail": "This page does not contain a visible H1 heading.",
            },
        )
        store.update_scan(
            current["id"],
            status="completed",
            completed_at="2026-07-27T11:00:00+00:00",
            summary={"health_score": 90},
        )

        details = store.scan_details(current["id"])

        self.assertEqual(details["findings"][0]["confidence"], "confirmed")
        self.assertEqual(details["findings"][0]["owner"], "SEO / Content")
        self.assertEqual(len(details["issue_groups"]), 1)
        self.assertEqual(details["comparison"]["baseline"]["id"], baseline["id"])
        self.assertEqual(
            details["comparison"]["counts"],
            {"new": 1, "fixed": 1, "recurring": 0, "unchanged": 0},
        )

    def test_page_priority_is_inferred_overridden_and_reused_by_future_scans(self) -> None:
        first = store.create_scan("https://example.com", 3, 1)
        page_url = "https://example.com/checkout"
        page = {
            "url": page_url,
            "final_url": page_url,
            "depth": 1,
            "status": 200,
            "title": "Checkout",
            "h1": "Checkout",
            "meta_description": "Complete purchase",
            "load_ms": 100,
            "screenshot_path": None,
            "error_type": None,
            "error_detail": None,
            "redirect_chain": [],
            "console": [],
            "network": [],
            "links": [],
        }
        store.save_page(first["id"], page)
        self.assertEqual(store.scan_details(first["id"])["pages"][0]["priority"], "critical")

        self.assertTrue(store.set_page_priority(first["id"], page_url, "high_value"))
        second = store.create_scan("https://example.com", 3, 1)
        store.save_page(second["id"], page)

        self.assertEqual(store.scan_details(second["id"])["pages"][0]["priority"], "high_value")

    def test_report_settings_and_share_records_are_persistent(self) -> None:
        scan = store.create_scan("https://example.com", 3, 1)

        self.assertTrue(
            store.update_report_settings(scan["id"], "Quality Agency", "Release report", "#123456")
        )
        store.create_report_share(
            "share-token",
            scan["id"],
            "executive",
            None,
            "2026-08-01T10:00:00+00:00",
        )

        updated = store.get_scan(scan["id"])
        share = store.get_report_share("share-token")
        self.assertEqual(updated["agency_name"], "Quality Agency")
        self.assertEqual(updated["brand_color"], "#123456")
        self.assertEqual(share["scan_id"], scan["id"])
        self.assertEqual(share["report_kind"], "executive")

    def test_content_configuration_and_site_analysis_are_persistent(self) -> None:
        scan = store.create_scan(
            "https://example.com",
            3,
            1,
            {"duplicate_titles": False, "short_content_words": 150},
        )
        store.update_scan(
            scan["id"],
            site_analysis={"sitemap_url_count": 12, "orphan_pages": ["https://example.com/orphan"]},
        )

        saved = store.get_scan(scan["id"])

        self.assertFalse(saved["content_checks"]["duplicate_titles"])
        self.assertEqual(saved["content_checks"]["short_content_words"], 150)
        self.assertEqual(saved["site_analysis"]["sitemap_url_count"], 12)


if __name__ == "__main__":
    unittest.main()
