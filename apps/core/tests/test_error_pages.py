from django.urls import reverse

from apps.core.testing import SchoolTestCase


class ErrorPageTests(SchoolTestCase):
    """Error pages fit both layouts: the sign-in screen for visitors and the app for staff."""

    def test_not_found_for_visitors_and_signed_in_users(self):
        response = self.client.get("/no-such-page/")
        self.assertContains(response, "This page is not available.", status_code=404)
        self.sign_in(self.admin)
        response = self.client.get("/no-such-page/")
        self.assertContains(response, "This record is not available.", status_code=404)

    def test_forbidden_page_keeps_the_app_layout(self):
        self.sign_in(self.teacher)
        response = self.client.get(reverse("users"))
        self.assertContains(response, "You do not have access to this action.", status_code=403)
        self.assertContains(response, 'aria-label="Main navigation"', status_code=403)
