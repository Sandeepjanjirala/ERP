from django.core import mail
from django.test import override_settings
from django.urls import reverse

from apps.core.testing import PASSWORD, SchoolTestCase


class AuthenticationTests(SchoolTestCase):
    """Sign-in, throttling, password changes and resets, deactivation."""

    def test_login_required_for_all_portal_pages(self):
        for url in [
            "/",
            "/students/",
            "/attendance/",
            "/exams/",
            "/reports/",
            "/setup/",
            "/users/",
            "/activity/",
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 302)

    def test_wrong_password_and_rate_limit(self):
        for _ in range(8):
            self.assertEqual(
                self.client.post(
                    reverse("login"), {"username": "teacher", "password": "wrong"}
                ).status_code,
                200,
            )
        self.assertEqual(
            self.client.post(
                reverse("login"), {"username": "teacher", "password": PASSWORD}
            ).status_code,
            429,
        )

    def test_normalized_login_and_password_hash(self):
        response = self.client.post(reverse("login"), {"username": "TEACHER", "password": PASSWORD})
        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(self.teacher.password, PASSWORD)
        self.assertTrue(self.teacher.check_password(PASSWORD))

    def test_get_cannot_logout_or_change_account(self):
        self.sign_in(self.admin)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertEqual(
            self.client.get(reverse("toggle_user", args=[self.teacher.pk])).status_code, 405
        )

    def test_first_password_change_is_mandatory(self):
        self.teacher.must_change_password = True
        self.teacher.save()
        self.sign_in(self.teacher)
        self.assertRedirects(
            self.client.get("/"), reverse("password_change"), fetch_redirect_response=False
        )

    def test_inactive_account_cannot_login(self):
        self.teacher.is_active = False
        self.teacher.save()
        self.client.post(reverse("login"), {"username": "teacher", "password": PASSWORD})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_deactivation_revokes_existing_session(self):
        self.sign_in(self.teacher)
        self.teacher.is_active = False
        self.teacher.save()
        self.assertEqual(self.client.get("/").status_code, 302)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_password_reset_sends_link_without_disclosing_unknown_account(self):
        known = self.client.post(reverse("password_reset"), {"email": self.teacher.email})
        unknown = self.client.post(reverse("password_reset"), {"email": "unknown@example.com"})
        self.assertEqual(known.status_code, 302)
        self.assertEqual(known.url, unknown.url)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/accounts/password/reset/", mail.outbox[0].body)

    def test_unicode_login_rate_limit_uses_normalized_username(self):
        from apps.accounts.throttling import throttle

        for _ in range(8):
            throttle("portal-login", "teacher")
        allowed, _ = throttle("portal-login", "ｔｅａｃｈｅｒ")
        self.assertFalse(allowed)

    def test_password_change_completes_forced_change(self):
        self.teacher.must_change_password = True
        self.teacher.save()
        self.sign_in(self.teacher)
        new_password = "A-new-testing-passphrase-94302!"
        response = self.client.post(
            reverse("password_change"),
            {
                "old_password": PASSWORD,
                "new_password1": new_password,
                "new_password2": new_password,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.teacher.refresh_from_db()
        self.assertFalse(self.teacher.must_change_password)
        self.assertTrue(self.teacher.check_password(new_password))
        self.assertEqual(self.client.get("/").status_code, 200)
