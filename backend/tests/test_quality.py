import unittest

from app.quality import (
    DEFAULT_CONTENT_CHECKS,
    aggregate_quality_findings,
    page_content_findings,
    parse_sitemap_document,
    robots_sitemap_locations,
)


class SitemapParsingTests(unittest.TestCase):
    def test_parses_urlset_and_sitemap_index(self) -> None:
        urls, nested = parse_sitemap_document(
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://example.com/a</loc></url></urlset>'
        )
        index_urls, index_nested = parse_sitemap_document(
            '<sitemapindex><sitemap><loc>https://example.com/posts.xml</loc></sitemap></sitemapindex>'
        )

        self.assertEqual(urls, ["https://example.com/a"])
        self.assertEqual(nested, [])
        self.assertEqual(index_urls, [])
        self.assertEqual(index_nested, ["https://example.com/posts.xml"])

    def test_reads_sitemap_directives_from_robots(self) -> None:
        locations = robots_sitemap_locations(
            "User-agent: *\nSitemap: /main-sitemap.xml\nSITEMAP: https://example.com/news.xml",
            "https://example.com/",
        )
        self.assertEqual(
            locations,
            ["https://example.com/main-sitemap.xml", "https://example.com/news.xml"],
        )


class ContentQualityTests(unittest.TestCase):
    def test_page_checks_detect_headings_thin_placeholder_alt_and_canonical(self) -> None:
        findings = page_content_findings(
            "https://example.com/page",
            {
                "h1_count": 2,
                "word_count": 5,
                "placeholder_matches": ["lorem ipsum"],
                "images_missing_alt": ["/hero.png"],
                "images_missing_alt_count": 3,
                "canonical_urls": ["https://other.example/page"],
                "noindex": True,
            },
            DEFAULT_CONTENT_CHECKS,
        )
        titles = {finding["title"] for finding in findings}

        self.assertIn("Multiple H1 headings", titles)
        self.assertIn("Page has almost no content", titles)
        self.assertIn("Placeholder text is visible", titles)
        self.assertIn("Images are missing alternative text", titles)
        self.assertIn("Canonical points outside the website", titles)
        self.assertIn("Page is marked noindex", titles)

    def test_disabled_check_does_not_create_finding(self) -> None:
        settings = {**DEFAULT_CONTENT_CHECKS, "missing_image_alt": False}
        findings = page_content_findings(
            "https://example.com",
            {
                "h1_count": 1,
                "word_count": 200,
                "placeholder_matches": [],
                "images_missing_alt": ["/hero.png"],
                "canonical_urls": [],
                "noindex": False,
            },
            settings,
        )
        self.assertFalse(any("alternative text" in finding["title"] for finding in findings))


class FakePolicy:
    def allows(self, url: str) -> bool:
        return not url.endswith("/private")


class SiteReconciliationTests(unittest.TestCase):
    def test_reconciles_orphans_missing_sitemap_broken_noindex_and_robots(self) -> None:
        pages = [
            {
                "url": "https://example.com/",
                "status": 200,
                "title": "Home",
                "meta_description": "Home",
                "links": ["https://example.com/broken", "https://example.com/not-listed"],
                "quality": {},
            },
            {
                "url": "https://example.com/broken",
                "status": 404,
                "title": "Missing",
                "meta_description": "",
                "links": [],
                "quality": {},
            },
            {
                "url": "https://example.com/orphan",
                "status": 200,
                "title": "Orphan",
                "meta_description": "Orphan",
                "links": [],
                "quality": {"noindex": True},
            },
        ]
        sitemap = {
            "urls": ["https://example.com/", "https://example.com/orphan", "https://example.com/private"],
            "sources": ["https://example.com/sitemap.xml"],
            "errors": [],
            "truncated": False,
        }

        findings, analysis = aggregate_quality_findings(
            pages,
            sitemap,
            FakePolicy(),
            DEFAULT_CONTENT_CHECKS,
            "https://example.com/",
        )
        titles = {finding["title"] for finding in findings}

        self.assertIn("Broken internal link", titles)
        self.assertIn("Internally linked page missing from sitemap", titles)
        self.assertIn("Orphan page", titles)
        self.assertIn("Noindex page listed in sitemap", titles)
        self.assertIn("Sitemap URL blocked by robots.txt", titles)
        self.assertEqual(analysis["sitemap_url_count"], 3)
        self.assertEqual(analysis["sitemap_urls_unchecked"], 1)
        self.assertEqual(analysis["sitemap_status"], "valid")
        self.assertTrue(analysis["sitemap_comparison_available"])

    def test_explains_sitemap_response_without_page_urls(self) -> None:
        findings, analysis = aggregate_quality_findings(
            [],
            {
                "urls": [],
                "sources": ["https://example.com/?sitemap.xml"],
                "errors": [{"url": "https://example.com/sitemap.xml", "status": 404}],
                "truncated": False,
            },
            FakePolicy(),
            DEFAULT_CONTENT_CHECKS,
            "https://example.com/",
        )

        self.assertEqual(analysis["sitemap_status"], "empty_or_invalid")
        self.assertFalse(analysis["sitemap_comparison_available"])
        self.assertIn("no valid page URLs", analysis["sitemap_status_detail"])
        self.assertIn("Sitemap is empty or invalid", {finding["title"] for finding in findings})

    def test_distinguishes_missing_sitemap(self) -> None:
        findings, analysis = aggregate_quality_findings(
            [],
            {
                "urls": [],
                "sources": [],
                "errors": [{"url": "https://example.com/sitemap.xml", "status": 404}],
                "truncated": False,
            },
            FakePolicy(),
            DEFAULT_CONTENT_CHECKS,
            "https://example.com/",
        )

        self.assertEqual(analysis["sitemap_status"], "not_found")
        self.assertFalse(analysis["sitemap_comparison_available"])
        self.assertIn("XML sitemap not found", {finding["title"] for finding in findings})


if __name__ == "__main__":
    unittest.main()
