"""htmx is our own hash-checked file, configured so the strict CSP still holds."""

import base64
import hashlib
from pathlib import Path

from django.conf import settings
from django.urls import reverse

from apps.core.testing import SchoolTestCase

HTMX = Path(settings.BASE_DIR, "static", "vendor", "htmx", "htmx.min.js")
README = Path(settings.BASE_DIR, "static", "vendor", "README.md")


class HtmxTests(SchoolTestCase):
    def test_the_vendored_file_is_the_one_recorded(self):
        digest = base64.b64encode(hashlib.sha256(HTMX.read_bytes()).digest()).decode()
        self.assertIn(digest, README.read_text(encoding="utf-8"))

    def test_signed_in_pages_load_it_safely_and_the_policy_is_unchanged(self):
        self.client.force_login(self.teacher)
        page = self.client.get(reverse("dashboard"))
        html = page.content.decode()
        self.assertIn("vendor/htmx/htmx.min.js", html)
        self.assertIn('"allowEval": false', html)
        self.assertIn('"allowScriptTags": false', html)
        self.assertIn("hx-headers", html)  # the CSRF token travels with htmx requests
        policy = page["Content-Security-Policy"]
        self.assertIn("script-src 'self';", policy)
        self.assertNotIn("unsafe-eval", policy)
        self.client.logout()
        self.assertNotIn("htmx", self.client.get(reverse("login")).content.decode())

    def test_lists_filter_live_and_still_work_as_plain_forms(self):
        self.client.force_login(self.admin)
        for url in (reverse("students"), reverse("fees")):
            with self.subTest(url=url):
                html = self.client.get(url).content.decode()
                self.assertIn('hx-select="#results"', html)
                self.assertIn('id="results"', html)
        # The request htmx makes is the ordinary GET: the server filters as before.
        page = self.client.get(reverse("students"), {"q": "alice"}, HTTP_HX_REQUEST="true")
        self.assertEqual([s.user.username for s in page.context["page_obj"]], ["alice"])
