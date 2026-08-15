import unittest

from app.security import passive_security_findings


class PassiveSecurityFindingTests(unittest.TestCase):
    def test_missing_headers_are_grouped_into_one_plain_finding(self) -> None:
        findings = passive_security_findings("https://example.com/", "https://example.com/", {}, {})

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["category"], "security")
        self.assertEqual(findings[0]["title"], "Common browser security protections are incomplete")
        self.assertIn("HTTPS enforcement", findings[0]["detail"])
        self.assertIn("not proof", findings[0]["detail"])

    def test_complete_headers_do_not_create_header_finding(self) -> None:
        findings = passive_security_findings(
            "https://example.com/", "https://example.com/",
            {
                "strict-transport-security": "max-age=31536000",
                "content-security-policy": "default-src 'self'; frame-ancestors 'none'",
                "x-content-type-options": "nosniff",
                "referrer-policy": "strict-origin-when-cross-origin",
            }, {},
        )
        self.assertEqual(findings, [])

    def test_insecure_page_form_and_password_are_reported(self) -> None:
        findings = passive_security_findings(
            "http://example.com/login", "http://example.com/login", {},
            {"insecure_form_actions": ["http://example.com/session"], "password_input_count": 1},
        )
        titles = {item["title"] for item in findings}
        self.assertIn("Website is not using HTTPS", titles)
        self.assertIn("A form sends information over an insecure connection", titles)
        self.assertIn("Password field is shown without HTTPS", titles)

    def test_mixed_active_content_is_high_severity(self) -> None:
        findings = passive_security_findings(
            "https://example.com/", "https://example.com/",
            {
                "strict-transport-security": "max-age=31536000",
                "content-security-policy": "default-src 'self'; frame-ancestors 'none'",
                "x-content-type-options": "nosniff",
                "referrer-policy": "same-origin",
            },
            {"insecure_resources": ["http://cdn.example.com/app.js"], "active_insecure_resource_count": 1},
        )
        self.assertEqual(findings[0]["title"], "Secure page loads content over an insecure connection")
        self.assertEqual(findings[0]["severity"], "high")

    def test_only_first_party_sensitive_cookies_are_checked(self) -> None:
        findings = passive_security_findings(
            "https://example.com/", "https://example.com/",
            {
                "strict-transport-security": "max-age=31536000",
                "content-security-policy": "default-src 'self'; frame-ancestors 'none'",
                "x-content-type-options": "nosniff",
                "referrer-policy": "same-origin",
            }, {},
            [
                {"name": "session_id", "domain": ".example.com", "secure": False, "httpOnly": False},
                {"name": "session_id", "domain": ".analytics.test", "secure": False, "httpOnly": False},
                {"name": "theme", "domain": ".example.com", "secure": False, "httpOnly": False},
            ],
            check_cookies=True,
        )
        self.assertEqual(len(findings), 2)
        self.assertTrue(all("cookie" in item["title"].lower() for item in findings))


if __name__ == "__main__":
    unittest.main()
