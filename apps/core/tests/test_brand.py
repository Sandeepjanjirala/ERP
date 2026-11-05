from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.core.testing import PASSWORD
from apps.organization.models import Branch, Organization


class BrandTests(TestCase):
    """EduNexa is the product name everywhere; a school's own name is data, not branding."""

    @classmethod
    def setUpTestData(cls):
        org = Organization.objects.create(name="Greenfield Group of Schools")
        branch = Branch.objects.create(
            organization=org, name="North", code="north", city="Hyderabad"
        )
        cls.admin = User.objects.create_user(
            "admin",
            "admin@example.com",
            PASSWORD,
            role="admin",
            branch=branch,
            must_change_password=False,
        )

    def test_page_title_uses_product_name_and_school_is_the_workspace(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "<title>Overview · EduNexa</title>")
        self.assertNotContains(response, "<title>Overview · Greenfield")
        self.assertContains(response, "Greenfield Group of Schools<small>North</small>")

    def test_login_page_is_branded(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, "<title>Sign in · EduNexa</title>")
        self.assertContains(response, "Sign in to EduNexa.")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_password_reset_email_is_branded(self):
        self.client.post(reverse("password_reset"), {"email": self.admin.email})
        self.assertEqual(mail.outbox[0].subject, "Reset your EduNexa password")
        self.assertIn("your EduNexa account", mail.outbox[0].body)
