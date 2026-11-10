"""Demo mode: one-click logins, the banner, and a nightly reset that can't touch real data."""

from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.core.testing import SchoolTestCase
from apps.demo.models import DemoMarker
from apps.demo.services import NotADemoDatabase, reset_demo
from apps.organization.models import Organization


def seed():
    with override_settings(DEMO_MODE=True):
        call_command("seed_demo", "--size", "small", stdout=StringIO())


class ResetGuardTests(SchoolTestCase):
    """A database seed_demo didn't create: the reset must leave it alone."""

    def test_the_reset_needs_demo_mode(self):
        DemoMarker.objects.create()  # even with the marker
        with self.assertRaisesMessage(NotADemoDatabase, "only with DEMO_MODE=1"):
            reset_demo("small")
        self.assertTrue(User.objects.filter(username="alice").exists())

    @override_settings(DEMO_MODE=True)
    def test_the_reset_refuses_a_database_without_the_marker(self):
        with self.assertRaisesMessage(NotADemoDatabase, "not created by seed_demo"):
            reset_demo("small")
        with self.assertRaisesMessage(CommandError, "not created by seed_demo"):
            call_command("reset_demo", "--size", "small")
        self.assertTrue(User.objects.filter(username="alice").exists())
        self.assertEqual(Organization.objects.get().name, "Test Organisation")

    def test_seeding_is_refused_outside_development_and_demo_mode(self):
        with self.assertRaisesMessage(CommandError, "only in development or with DEMO_MODE=1"):
            call_command("seed_demo", "--size", "small")

    @override_settings(DEMO_MODE=True)
    def test_seeding_never_marks_a_database_that_has_data(self):
        with self.assertRaisesMessage(CommandError, "requires an empty database"):
            call_command("seed_demo", "--size", "small")
        self.assertFalse(DemoMarker.objects.exists())


@override_settings(DEMO_MODE=True)
class ResetTests(TestCase):
    def setUp(self):
        seed()

    def test_the_reset_replaces_everything_with_a_fresh_seed(self):
        self.assertEqual(DemoMarker.objects.count(), 1)
        User.objects.create_user(
            "visitor-made",
            "v@example.invalid",
            role="teacher",
            branch=User.objects.get(username="admin.madhapur").branch,
        )
        reset_demo("small")
        self.assertFalse(User.objects.filter(username="visitor-made").exists())
        self.assertTrue(User.objects.filter(username="teacher.madhapur").exists())
        self.assertEqual(DemoMarker.objects.count(), 1)

    def test_a_failed_reset_changes_nothing(self):
        before = User.objects.count()
        with mock.patch(
            "apps.demo.management.commands.seed_demo.Command.seed_announcements",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(RuntimeError):
                reset_demo("small")
        self.assertEqual(User.objects.count(), before)
        self.assertEqual(DemoMarker.objects.count(), 1)

    def test_one_click_logins(self):
        for role, username in (("teacher", "teacher.madhapur"), ("parent", "parent1.madhapur")):
            with self.subTest(role=role):
                response = self.client.post(reverse("demo_login", args=[role]))
                self.assertRedirects(response, reverse("dashboard"))
                self.assertEqual(
                    int(self.client.session["_auth_user_id"]),
                    User.objects.get(username=username).pk,
                )
                self.client.logout()
        self.assertEqual(self.client.get(reverse("demo_login", args=["teacher"])).status_code, 405)
        self.assertEqual(self.client.post(reverse("demo_login", args=["root"])).status_code, 404)

    def test_a_switched_off_demo_account_explains_itself(self):
        User.objects.filter(username="teacher.madhapur").update(is_active=False)
        response = self.client.post(reverse("demo_login", args=["teacher"]), follow=True)
        self.assertContains(response, "comes back at the nightly reset")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_the_sign_in_page_and_banner(self):
        page = self.client.get(reverse("login"))
        self.assertContains(page, "Try the demo as")
        self.assertContains(page, reverse("demo_login", args=["accountant"]))
        self.client.post(reverse("demo_login", args=["admin"]))
        self.assertContains(
            self.client.get(reverse("dashboard")), "Synthetic data, reset every night"
        )


class NotTheDemoTests(SchoolTestCase):
    def test_no_one_click_logins_or_banner_outside_demo_mode(self):
        DemoMarker.objects.create()
        self.assertEqual(self.client.post(reverse("demo_login", args=["teacher"])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("login")), "Try the demo as")
        self.sign_in(self.admin)
        self.assertNotContains(self.client.get(reverse("dashboard")), "Synthetic data")

    @override_settings(DEMO_MODE=True)
    def test_no_one_click_logins_on_a_database_without_the_marker(self):
        self.assertEqual(self.client.post(reverse("demo_login", args=["admin"])).status_code, 404)
