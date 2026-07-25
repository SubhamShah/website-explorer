import unittest

from app.crawler import RobotsPolicy, normalize_url, same_site


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


class RobotsPolicyTests(unittest.TestCase):
    def test_conservative_policy_can_stop_all_crawling(self) -> None:
        policy = RobotsPolicy(None, "unavailable", "temporary failure", disallow_all=True)
        self.assertFalse(policy.allows("https://example.com"))


if __name__ == "__main__":
    unittest.main()
