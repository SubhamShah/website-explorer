import tempfile
import unittest
from pathlib import Path

from app.accessibility import accessibility_findings, capture_element_evidence, wcag_metadata


class AccessibilityFindingTests(unittest.TestCase):
    def test_converts_axe_violation_to_plain_language_evidence(self) -> None:
        findings, summary = accessibility_findings(
            "https://example.com/signup",
            {
                "violations": [
                    {
                        "id": "image-alt",
                        "impact": "critical",
                        "tags": ["cat.text-alternatives", "wcag2a", "wcag111"],
                        "help": "Images must have alternate text",
                        "helpUrl": "https://dequeuniversity.com/rules/axe/image-alt",
                        "nodes": [
                            {
                                "target": ["header img.logo"],
                                "html": '<img class="logo" src="/logo.png">',
                                "failureSummary": "Fix any of the following: Element does not have an alt attribute",
                            }
                        ],
                    }
                ]
            },
            "scan-desktop.png",
        )

        self.assertEqual(summary["violation_count"], 1)
        self.assertEqual(summary["affected_element_count"], 1)
        self.assertEqual(findings[0]["severity"], "critical")
        self.assertEqual(findings[0]["metadata"]["axe_rule_id"], "image-alt")
        self.assertEqual(findings[0]["metadata"]["wcag_criteria"], ["1.1.1"])
        self.assertEqual(findings[0]["metadata"]["wcag_level"], "Level A")
        self.assertEqual(findings[0]["metadata"]["component_hint"], "shared header component")
        self.assertIn("cannot see this image", findings[0]["metadata"]["why_it_matters"])
        self.assertIn("text alternative", findings[0]["metadata"]["plain_problem"])
        self.assertIn("meaningful alt description", findings[0]["metadata"]["recommended_action"])
        self.assertIn("alt attribute", findings[0]["metadata"]["failure_summary"])

    def test_reports_highest_wcag_level_and_best_practice(self) -> None:
        criteria, level = wcag_metadata(["wcag2a", "wcag21aa", "wcag143"])
        best_practice_criteria, best_practice_level = wcag_metadata(["best-practice"])

        self.assertEqual(criteria, ["1.4.3"])
        self.assertEqual(level, "Level AA")
        self.assertEqual(best_practice_criteria, [])
        self.assertEqual(best_practice_level, "Best practice")

    def test_uses_short_fix_instead_of_raw_axe_failure_list(self) -> None:
        findings, _ = accessibility_findings(
            "https://example.com/form",
            {
                "violations": [{
                    "id": "button-name",
                    "impact": "critical",
                    "tags": ["wcag2a", "wcag412"],
                    "help": "Buttons must have discernible text",
                    "nodes": [{
                        "target": ["button.icon"],
                        "html": "<button class=\"icon\"></button>",
                        "failureSummary": "Fix any of the following: Element has no inner text; aria-label is empty; title is missing",
                    }],
                }]
            },
            None,
        )

        metadata = findings[0]["metadata"]
        self.assertEqual(
            metadata["plain_problem"],
            "This button has no name that a screen reader can announce.",
        )
        self.assertIn("visible text or a short aria-label", metadata["plain_fix"])
        self.assertNotIn("title is missing", metadata["recommended_action"])


class ElementEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_attaches_human_location_and_element_screenshot(self) -> None:
        class FakeLocator:
            first = None

            def __init__(self) -> None:
                self.first = self
                self.saved_path = None

            async def count(self) -> int:
                return 1

            async def evaluate(self, _script: str) -> dict:
                return {
                    "elementLabel": "Button “Question 1”",
                    "pageSection": "Quiz section",
                }

            async def bounding_box(self) -> dict:
                return {"x": 10.123, "y": 20, "width": 90, "height": 36}

            async def is_visible(self) -> bool:
                return True

            async def screenshot(self, path: str) -> None:
                self.saved_path = path

        class FakePage:
            def __init__(self) -> None:
                self.element = FakeLocator()

            def locator(self, _selector: str) -> FakeLocator:
                return self.element

        findings = [{"metadata": {"affected_element": "button.icon"}}]
        page = FakePage()
        with tempfile.TemporaryDirectory() as directory:
            await capture_element_evidence(
                page,
                findings,
                Path(directory),
                "scan-page",
            )

        metadata = findings[0]["metadata"]
        self.assertEqual(metadata["element_label"], "Button “Question 1”")
        self.assertEqual(metadata["page_section"], "Quiz section")
        self.assertEqual(metadata["element_screenshot_path"], "scan-page-a11y-1.png")
        self.assertEqual(metadata["bounding_box"]["x"], 10.1)
        self.assertTrue(page.element.saved_path.endswith("scan-page-a11y-1.png"))


if __name__ == "__main__":
    unittest.main()
