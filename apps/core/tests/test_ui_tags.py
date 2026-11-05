from types import SimpleNamespace

from django.template import Context, Template
from django.test import SimpleTestCase

from apps.core.templatetags.ui import icon, pretty_json


class UiTagTests(SimpleTestCase):
    def test_icon_is_decorative_unless_labelled(self):
        decorative = icon("grid")
        self.assertIn('aria-hidden="true"', decorative)
        self.assertIn('icons.svg#grid"', decorative)
        labelled = icon("alert", label="Warning <b>")
        self.assertIn('role="img"', labelled)
        self.assertIn('aria-label="Warning &lt;b&gt;"', labelled)  # labels are escaped

    def test_aria_current_matches_url_names(self):
        template = Template("{% load ui %}<a{% aria_current 'exams' 'exam_detail' %}>")
        current = SimpleNamespace(resolver_match=SimpleNamespace(url_name="exam_detail"))
        other = SimpleNamespace(resolver_match=SimpleNamespace(url_name="dashboard"))
        self.assertEqual(template.render(Context({"request": current})), '<a aria-current="page">')
        self.assertEqual(template.render(Context({"request": other})), "<a>")
        self.assertEqual(template.render(Context({})), "<a>")  # error pages may have no match

    def test_pretty_json_is_indented_and_sorted(self):
        self.assertEqual(pretty_json({"b": 1, "a": "é"}), '{\n  "a": "é",\n  "b": 1\n}')
