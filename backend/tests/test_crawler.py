import unittest

from app.crawler import (
    RobotsPolicy,
    calculate_health_score,
    classify_console_item,
    classify_network_item,
    console_finding,
    network_finding,
    network_request_actionable,
    network_request_failed,
    normalize_links,
    normalize_url,
    same_site,
    should_retry_page_status,
)


class UrlNormalizationTests(unittest.TestCase):
    def test_normalizes_equivalent_urls(self) -> None:
        variants = [
            "HTTPS://Example.COM:443/docs/",
            "https://example.com/docs#overview",
            "https://example.com/a/../docs?utm_source=test",
        ]
        self.assertEqual({normalize_url(item) for item in variants}, {"https://example.com/docs"})

    def test_sorts_meaningful_query_parameters(self) -> None:
        self.assertEqual(
            normalize_url("https://example.com/search?b=2&utm_medium=email&a=1"),
            "https://example.com/search?a=1&b=2",
        )

    def test_same_site_requires_exact_host_and_port(self) -> None:
        origin = "https://example.com"
        self.assertTrue(same_site("https://example.com/about", origin))
        self.assertFalse(same_site("https://www.example.com/about", origin))
        self.assertFalse(same_site("http://example.com/about", origin))
        self.assertFalse(same_site("https://example.com:444/about", origin))

    def test_malformed_link_values_do_not_abort_discovery(self) -> None:
        links = normalize_links(
            [
                "/about",
                {"unexpected": "object"},
                None,
                "https://example.com/contact#form",
                "https://other.example/path",
            ],
            "https://example.com",
        )
        self.assertEqual(links, ["https://example.com/about", "https://example.com/contact"])

    def test_transient_and_not_found_page_statuses_are_retried(self) -> None:
        self.assertTrue(should_retry_page_status(404))
        self.assertTrue(should_retry_page_status(503))
        self.assertFalse(should_retry_page_status(200))
        self.assertFalse(should_retry_page_status(301))


class RobotsPolicyTests(unittest.TestCase):
    def test_conservative_policy_can_stop_all_crawling(self) -> None:
        policy = RobotsPolicy(None, "unavailable", "temporary failure", disallow_all=True)
        self.assertFalse(policy.allows("https://example.com"))


class NetworkFindingTests(unittest.TestCase):
    def test_successful_api_response_is_informational(self) -> None:
        item = {"method": "GET", "url": "https://example.com/api/items", "status": 200, "resource_type": "fetch"}
        finding = network_finding("https://example.com", item)
        self.assertEqual(finding["severity"], "info")
        self.assertEqual(finding["title"], "First-party API request passed")
        self.assertFalse(network_request_failed(item))

    def test_failed_resource_response_is_high_severity(self) -> None:
        item = {"method": "GET", "url": "https://example.com/app.js", "status": 503, "resource_type": "script"}
        finding = network_finding("https://example.com", item)
        self.assertEqual(finding["severity"], "high")
        self.assertEqual(finding["title"], "First-party Script request failed")
        self.assertTrue(network_request_failed(item))

    def test_transport_failure_includes_error(self) -> None:
        item = {"method": "POST", "url": "https://example.com/api/save", "status": "failed", "resource_type": "xhr", "error": "connection reset"}
        finding = network_finding("https://example.com", item)
        self.assertIn("connection reset", finding["detail"])
        self.assertTrue(network_request_failed(item))

    def test_analytics_failure_is_informational_and_not_actionable(self) -> None:
        item = classify_network_item(
            "https://stablecluster.com/blog",
            {
                "method": "POST",
                "url": "https://www.google.com/rmkt/collect/123",
                "status": "failed",
                "resource_type": "fetch",
                "error": "net::ERR_FAILED",
            },
        )
        self.assertEqual(item["classification"], "advertising_analytics")
        self.assertEqual(item["severity"], "info")
        self.assertFalse(network_request_actionable(item))

    def test_scanner_blocked_turnstile_is_informational(self) -> None:
        item = classify_network_item(
            "https://stablecluster.com/google-workspace",
            {
                "method": "GET",
                "url": "https://challenges.cloudflare.com/cdn-cgi/challenge",
                "status": "failed",
                "resource_type": "document",
                "error": "net::ERR_BLOCKED_BY_CLIENT",
                "blocked_by_crawler": True,
            },
        )
        finding = network_finding("https://stablecluster.com/google-workspace", item)
        self.assertEqual(item["classification"], "security_challenge")
        self.assertEqual(item["severity"], "info")
        self.assertFalse(network_request_actionable(item))
        self.assertEqual(finding["title"], "Security challenge Document request blocked by scanner")

    def test_aborted_first_party_font_is_informational(self) -> None:
        item = classify_network_item(
            "https://stablecluster.com/blog",
            {
                "method": "GET",
                "url": "https://stablecluster.com/font.woff",
                "status": "failed",
                "resource_type": "font",
                "error": "net::ERR_ABORTED",
            },
        )
        self.assertEqual(item["failure_kind"], "browser_aborted")
        self.assertEqual(item["severity"], "info")
        self.assertFalse(network_request_actionable(item))

    def test_failed_live_chat_is_medium_and_actionable(self) -> None:
        item = classify_network_item(
            "https://stablecluster.com",
            {
                "method": "GET",
                "url": "https://embed.tawk.to/widget",
                "status": "failed",
                "resource_type": "script",
                "error": "net::ERR_FAILED",
            },
        )
        self.assertEqual(item["classification"], "live_chat")
        self.assertEqual(item["severity"], "medium")
        self.assertTrue(network_request_actionable(item))


class HealthScoreTests(unittest.TestCase):
    def test_healthy_scan_scores_100(self) -> None:
        score, details = calculate_health_score([], 20, 1000, 0, max_pages=25)
        self.assertEqual(score, 100)
        self.assertEqual(sum(details["deductions"].values()), 0)
        self.assertEqual(details["method_version"], "2.1")
        self.assertEqual(details["coverage"]["confidence"], "comprehensive")

    def test_score_is_normalized_by_scan_size_and_request_volume(self) -> None:
        findings = [
            {"category": "seo", "severity": "low"},
            {"category": "console", "severity": "medium"},
            {"category": "performance", "severity": "medium"},
            {"category": "page", "severity": "high"},
        ]
        score, details = calculate_health_score(findings, 20, 1000, 17)
        self.assertGreater(score, 0)
        self.assertLess(score, 100)
        self.assertGreater(details["categories"]["reliability"]["deduction"], 0)

    def test_correlated_console_message_is_not_penalized_twice(self) -> None:
        related = {
            "category": "console",
            "severity": "high",
            "related_request_url": "https://example.com/app.js",
        }
        score, details = calculate_health_score([related], 1, 1, 1)
        self.assertEqual(details["categories"]["reliability"]["finding_count"], 1)
        self.assertLess(score, 100)

    def test_generic_failed_resource_line_is_supporting_evidence_not_a_second_penalty(self) -> None:
        findings = [
            {
                "category": "console",
                "severity": "medium",
                "page_url": "https://example.com",
                "title": "Browser error",
                "detail": "Access to script at 'https://chat.example/widget' was blocked by CORS policy.",
            },
            {
                "category": "console",
                "severity": "medium",
                "page_url": "https://example.com",
                "title": "Browser error",
                "detail": "Failed to load resource: net::ERR_FAILED",
            },
        ]

        _, details = calculate_health_score(findings, 1)

        self.assertEqual(details["categories"]["reliability"]["finding_count"], 1)

    def test_severity_and_page_importance_increase_business_impact(self) -> None:
        standard_score, _ = calculate_health_score(
            [{"category": "page", "severity": "low", "page_url": "https://example.com/blog/news"}],
            20,
        )
        critical_score, details = calculate_health_score(
            [{"category": "page", "severity": "critical", "page_url": "https://example.com/checkout"}],
            20,
        )
        self.assertLess(critical_score, standard_score)
        self.assertEqual(details["top_impacts"][0]["priority_multiplier"], 3.0)

    def test_unselected_categories_do_not_change_the_score(self) -> None:
        options = {
            "page_health": True,
            "network": False,
            "console": False,
            "performance": False,
            "seo": False,
            "sitemap_indexing": False,
            "accessibility": False,
            "content_quality": False,
            "responsive": False,
        }
        score, details = calculate_health_score(
            [{"category": "accessibility", "severity": "critical", "page_url": "https://example.com"}],
            5,
            scan_options=options,
        )
        self.assertEqual(score, 100)
        self.assertFalse(details["categories"]["accessibility"]["checked"])
        self.assertEqual(details["coverage"]["confidence"], "focused")

    def test_selected_passive_security_has_its_own_health_category(self) -> None:
        options = {
            "page_health": False,
            "network": False,
            "console": False,
            "performance": False,
            "seo": False,
            "sitemap_indexing": False,
            "accessibility": False,
            "content_quality": False,
            "responsive": False,
            "passive_security": True,
        }
        score, details = calculate_health_score(
            [{
                "category": "security",
                "severity": "high",
                "page_url": "https://example.com/login",
                "title": "Sensitive cookie can travel without encryption",
            }],
            5,
            scan_options=options,
        )

        self.assertLess(score, 100)
        self.assertTrue(details["categories"]["security"]["checked"])
        self.assertEqual(details["categories"]["security"]["finding_count"], 1)

    def test_reaching_the_page_limit_marks_coverage_limited(self) -> None:
        _, details = calculate_health_score([], 25, max_pages=25)
        self.assertEqual(details["coverage"]["confidence"], "limited")


class ConsoleFindingTests(unittest.TestCase):
    def test_cors_console_message_is_classified_without_network_capture(self) -> None:
        item = classify_console_item(
            "https://example.com",
            {
                "level": "error",
                "message": "Access to script at 'https://embed.tawk.to/widget' was blocked by CORS policy.",
            },
            [],
        )
        finding = console_finding("https://example.com", item)

        self.assertEqual(item["classification"], "live_chat")
        self.assertEqual(item["related_request_url"], "https://embed.tawk.to/widget")
        self.assertIn("live chat", finding["title"])

    def test_resource_error_inherits_analytics_classification(self) -> None:
        network = [
            classify_network_item(
                "https://example.com",
                {
                    "method": "POST",
                    "url": "https://www.google.com/rmkt/collect/123",
                    "status": "failed",
                    "resource_type": "fetch",
                    "error": "net::ERR_FAILED",
                },
            )
        ]
        item = classify_console_item(
            "https://example.com",
            {
                "level": "error",
                "message": "Failed to load resource: net::ERR_FAILED",
                "location": {"url": "https://www.google.com/rmkt/collect/123"},
            },
            network,
        )
        finding = console_finding("https://example.com", item)
        self.assertEqual(item["classification"], "advertising_analytics")
        self.assertEqual(finding["severity"], "info")
        self.assertIn("Related request:", finding["detail"])

    def test_turnstile_origin_warning_is_scanner_side_effect(self) -> None:
        item = classify_console_item(
            "https://example.com",
            {
                "level": "warning",
                "message": "Failed to execute 'postMessage': target origin https://challenges.cloudflare.com does not match recipient origin ('null')",
                "location": {},
            },
            [],
        )
        finding = console_finding("https://example.com", item)
        self.assertEqual(item["classification"], "scanner_side_effect")
        self.assertEqual(finding["severity"], "info")

    def test_uncorrelated_console_error_remains_medium(self) -> None:
        item = classify_console_item(
            "https://example.com",
            {"level": "error", "message": "Application crashed", "location": {}},
            [],
        )
        self.assertEqual(item["classification"], "browser_console")
        self.assertEqual(item["severity"], "medium")


if __name__ == "__main__":
    unittest.main()
