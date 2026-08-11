import unittest

from app.responsive import responsive_findings


def viewport(width: int, height: int, **overrides: object) -> dict:
    return {
        "width": width,
        "height": height,
        "document_width": width,
        "viewport_width": width,
        "overflow_elements": [],
        "unreadable_text": [],
        "overlapping_elements": [],
        "images_outside_viewport": [],
        "hidden_content": [],
        "visible_nav_links": 5,
        "visible_interactive_elements": 10,
        "menu_control_visible": False,
        **overrides,
    }


class ResponsiveFindingTests(unittest.TestCase):
    def test_mobile_layout_failures_create_separate_actionable_findings(self) -> None:
        evidence = {
            "desktop": viewport(1440, 900),
            "tablet": viewport(768, 1024),
            "mobile": viewport(
                390,
                844,
                document_width=470,
                overflow_elements=["div.hero"],
                unreadable_text=["span.caption (10px)"],
                overlapping_elements=["button.buy overlaps a.help"],
                images_outside_viewport=["img.banner"],
                hidden_content=["main"],
                visible_nav_links=0,
            ),
        }

        findings = responsive_findings("https://example.com/checkout", evidence)
        titles = {finding["title"] for finding in findings}

        self.assertIn("Horizontal overflow on Mobile", titles)
        self.assertIn("Primary content hidden on Mobile", titles)
        self.assertIn("Elements overlap on Mobile", titles)
        self.assertIn("Small text on Mobile", titles)
        self.assertIn("Images extend outside Mobile viewport", titles)
        self.assertIn("Navigation may be broken on Mobile", titles)
        overflow = next(item for item in findings if item["title"] == "Horizontal overflow on Mobile")
        self.assertEqual(overflow["severity"], "high")
        self.assertIn("80px wider", overflow["detail"])

    def test_hidden_desktop_links_are_not_called_broken_when_menu_exists(self) -> None:
        evidence = {
            "desktop": viewport(1440, 900, visible_nav_links=6),
            "mobile": viewport(390, 844, visible_nav_links=0, menu_control_visible=True),
        }

        findings = responsive_findings("https://example.com", evidence)

        self.assertFalse(any("Navigation may be broken" in item["title"] for item in findings))

    def test_clipped_carousel_image_without_document_overflow_is_not_an_issue(self) -> None:
        evidence = {
            "desktop": viewport(1440, 900),
            "tablet": viewport(
                768,
                1024,
                document_width=768,
                images_outside_viewport=["img.carousel-slide"],
            ),
        }

        findings = responsive_findings("https://example.com/news", evidence)

        self.assertFalse(any("Images extend outside" in item["title"] for item in findings))

    def test_image_causing_real_document_overflow_remains_actionable(self) -> None:
        evidence = {
            "desktop": viewport(1440, 900),
            "mobile": viewport(
                390,
                844,
                document_width=450,
                overflow_elements=["img.hero"],
                images_outside_viewport=["img.hero"],
            ),
        }

        findings = responsive_findings("https://example.com", evidence)
        titles = {finding["title"] for finding in findings}

        self.assertIn("Horizontal overflow on Mobile", titles)
        self.assertIn("Images extend outside Mobile viewport", titles)


if __name__ == "__main__":
    unittest.main()
