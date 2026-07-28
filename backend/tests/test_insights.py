import unittest

from app.insights import build_issue_groups, compare_issue_groups, finding_fingerprint, finding_metadata, infer_page_priority


def finding(page_url: str, title: str = "Missing page title", detail: str = "No title") -> dict:
    return {
        "id": page_url,
        "page_url": page_url,
        "severity": "medium",
        "category": "seo",
        "title": title,
        "detail": detail,
    }


class FindingMetadataTests(unittest.TestCase):
    def test_seo_finding_has_plain_language_guidance(self) -> None:
        metadata = finding_metadata(finding("https://example.com/about"))

        self.assertEqual(metadata["confidence"], "confirmed")
        self.assertEqual(metadata["owner"], "SEO / Content")
        self.assertIn("HTML title", metadata["recommended_action"])
        self.assertTrue(metadata["why_it_matters"])
        self.assertTrue(metadata["verification"])

    def test_first_party_failure_is_assigned_to_developers(self) -> None:
        metadata = finding_metadata(
            {
                "severity": "high",
                "category": "network",
                "title": "First-party API request failed",
                "detail": "GET https://example.com/api/orders?request=983743 returned 500. Classification: first party.",
            }
        )

        self.assertEqual(metadata["confidence"], "confirmed")
        self.assertIn("developer", metadata["owner"].lower())
        self.assertIn("product-owned", metadata["why_it_matters"])

    def test_volatile_network_query_values_have_one_fingerprint(self) -> None:
        first = {
            "category": "network",
            "title": "First-party API request failed",
            "detail": "GET https://example.com/api/orders?random=100 returned 500. Classification: first party.",
        }
        second = {
            **first,
            "detail": "GET https://example.com/api/orders?random=999 returned 500. Classification: first party.",
        }

        self.assertEqual(finding_fingerprint(first), finding_fingerprint(second))


class IssueGroupingTests(unittest.TestCase):
    def test_important_commerce_paths_receive_automatic_priority(self) -> None:
        self.assertEqual(infer_page_priority("https://example.com/checkout"), "critical")
        self.assertEqual(infer_page_priority("https://example.com/services/cloud"), "high_value")
        self.assertEqual(infer_page_priority("https://example.com/blog/news"), "standard")

    def test_shared_template_becomes_one_developer_task(self) -> None:
        findings = []
        for index in range(3):
            item = finding(
                f"https://example.com/blog/article-{index}",
                title="Missing H1 heading",
            )
            item["metadata"] = {
                "template_id": "blog-article",
                "template_label": "Blog article template",
                "template_confidence": "high",
            }
            findings.append(item)

        groups = build_issue_groups(findings)

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["shared_origin"]["kind"], "template")
        self.assertEqual(groups[0]["shared_origin"]["label"], "Blog article template")
        self.assertEqual(groups[0]["shared_origin"]["affected_page_count"], 3)
        self.assertIn("Fix this once", groups[0]["recommended_action"])

    def test_repeated_root_cause_groups_affected_pages(self) -> None:
        groups = build_issue_groups(
            [
                finding("https://example.com/about"),
                finding("https://example.com/contact"),
            ]
        )

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["count"], 2)
        self.assertEqual(
            groups[0]["affected_pages"],
            ["https://example.com/about", "https://example.com/contact"],
        )

    def test_accessibility_group_keeps_a_quick_visual_locator(self) -> None:
        item = finding(
            "https://example.com/quiz",
            title="Accessibility: Buttons must have discernible text",
        )
        item["category"] = "accessibility"
        item["metadata"] = {
            "plain_problem": "This button has no accessible name.",
            "plain_fix": "Add visible text or an aria-label.",
            "element_label": "Unnamed button",
            "page_section": "Question 1 section",
            "element_screenshot_path": "scan-a11y-1.png",
            "affected_element": "button.icon",
            "axe_rule_id": "button-name",
        }

        group = build_issue_groups([item])[0]

        self.assertEqual(group["plain_problem"], "This button has no accessible name.")
        self.assertEqual(group["example_element_label"], "Unnamed button")
        self.assertEqual(group["example_page_section"], "Question 1 section")
        self.assertEqual(group["example_element_screenshot_path"], "scan-a11y-1.png")

    def test_comparison_marks_new_fixed_recurring_and_unchanged(self) -> None:
        stable_before = build_issue_groups([finding("https://example.com/a")])
        recurring_before = build_issue_groups(
            [finding("https://example.com/a", title="Missing H1 heading")]
        )
        fixed_before = build_issue_groups(
            [finding("https://example.com/a", title="Missing meta description")]
        )
        baseline = stable_before + recurring_before + fixed_before

        stable_now = build_issue_groups([finding("https://example.com/a")])
        recurring_now = build_issue_groups(
            [
                finding("https://example.com/a", title="Missing H1 heading"),
                finding("https://example.com/b", title="Missing H1 heading"),
            ]
        )
        new_now = build_issue_groups(
            [finding("https://example.com/a", title="Slow page load")]
        )
        comparison = compare_issue_groups(stable_now + recurring_now + new_now, baseline)

        self.assertEqual(
            comparison["counts"],
            {"new": 1, "fixed": 1, "recurring": 1, "unchanged": 1},
        )


if __name__ == "__main__":
    unittest.main()
