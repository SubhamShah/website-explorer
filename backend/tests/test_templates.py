import unittest

from app.templates import attach_template_metadata, template_metadata


class TemplateIntelligenceTests(unittest.TestCase):
    def test_recognizes_blog_and_service_templates(self) -> None:
        blog = template_metadata(
            "https://example.com/blog/accessible-checkout",
            ["header.site", "main", "article.post", "footer.site"],
        )
        service = template_metadata(
            "https://example.com/services/consulting",
            ["header.site", "main", "section.hero", "footer.site"],
        )

        self.assertEqual(blog["template_id"], "blog-article")
        self.assertEqual(blog["template_label"], "Blog article template")
        self.assertEqual(blog["template_confidence"], "high")
        self.assertTrue(blog["structure_signature"])
        self.assertEqual(service["template_label"], "Service page template")

    def test_attaches_page_template_to_findings(self) -> None:
        findings = [
            {
                "page_url": "https://example.com/blog/a",
                "title": "Missing H1 heading",
                "metadata": {},
            }
        ]
        pages = [
            {
                "url": "https://example.com/blog/a",
                "quality": {
                    "template": template_metadata("https://example.com/blog/a", ["main", "article"])
                },
            }
        ]

        attach_template_metadata(findings, pages)

        self.assertEqual(findings[0]["metadata"]["template_label"], "Blog article template")


if __name__ == "__main__":
    unittest.main()
