"""Every web page needs sign-in, except a short, reviewed list of public ones."""

import re

from django.test import TestCase
from django.urls import URLPattern, URLResolver, get_resolver

# Reviewed: these answer without signing in, and show no school data.
PUBLIC = {
    "accounts/login/",
    # Django's password-reset flow: request, "check your email", the emailed link (an invalid
    # or expired token shows only "this link is invalid"), and done.
    "accounts/password/reset/",
    "accounts/password/reset/sent/",
    "accounts/password/reset/<uidb64>/<token>/",
    "accounts/password/reset/complete/",
    "health/",  # database reachable or not; no records
    "api/schema/",
    "api/docs/",
    "api/redoc/",
}


def patterns(resolver=None, prefix=""):
    """Every concrete web route, with sample values for its parameters."""
    for entry in (resolver or get_resolver()).url_patterns:
        route = prefix + str(entry.pattern)
        if isinstance(entry, URLResolver):
            yield from patterns(entry, route)
        elif isinstance(entry, URLPattern):
            yield route, re.sub(r"<(?:\w+:)?(\w+)>", lambda m: "1", route)


class PublicSurfaceTests(TestCase):
    def test_only_the_reviewed_pages_are_public(self):
        checked = 0
        for route, path in patterns():
            if route.startswith("api/v1/"):
                continue  # every endpoint is in the API permission table (test_api_permissions)
            response = self.client.get("/" + path)
            checked += 1
            with self.subTest(route=route, status=response.status_code):
                if route in PUBLIC:
                    continue
                if response.status_code == 302:
                    self.assertTrue(response["Location"].startswith("/accounts/login/"))
                else:
                    # 286: the notification bell telling htmx to stop polling (no content).
                    self.assertIn(response.status_code, (401, 403, 404, 405, 286))
                    if response.status_code == 286:
                        self.assertEqual(response.content, b"")
        self.assertGreater(checked, 60)
