"""JWT sign-in, token lifecycle, the forced password change, and the API's error format."""

from apps.accounts.models import LoginAttempt
from apps.accounts.services import toggle_access
from apps.accounts.throttling import throttle
from apps.audit.models import AuditEvent
from apps.core.testing import PASSWORD, ApiTestCase

NEW_PASSWORD = "A-new-testing-passphrase-94302!"


class TokenTests(ApiTestCase):
    def test_sign_in_returns_a_token_pair_and_is_audited(self):
        tokens = self.sign_in_api(self.teacher)
        self.assertEqual(set(tokens), {"access", "refresh", "must_change_password"})
        self.assertFalse(tokens["must_change_password"])
        event = AuditEvent.objects.get(action="account.login", actor=self.teacher)
        self.assertEqual(event.details, {"via": "api"})

        self.bearer(tokens["access"])
        me = self.client.get("/api/v1/me/").json()
        self.assertEqual((me["username"], me["role"]), ("teacher", "teacher"))
        self.assertEqual(me["branch"]["code"], "north")

    def test_username_is_normalised_like_the_web_form(self):
        response = self.client.post(
            "/api/v1/auth/token/", {"username": "  TEACHER ", "password": PASSWORD}
        )
        self.assertEqual(response.status_code, 200)

    def test_wrong_password_uses_the_common_error_shape(self):
        response = self.client.post(
            "/api/v1/auth/token/", {"username": "teacher", "password": "wrong"}
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(set(response.json()), {"code", "detail"})
        self.assertEqual(response.json()["code"], "no_active_account")

    def test_missing_fields_report_each_field(self):
        response = self.client.post("/api/v1/auth/token/", {})
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["code"], "invalid")
        self.assertEqual(set(body["fields"]), {"username", "password"})

    def test_web_and_api_share_one_sign_in_limit(self):
        for _ in range(8):
            throttle("portal-login", "teacher")  # e.g. eight failed web sign-ins
        response = self.client.post(
            "/api/v1/auth/token/", {"username": "teacher", "password": PASSWORD}
        )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["code"], "throttled")

    def test_successful_sign_in_clears_the_counter(self):
        self.client.post("/api/v1/auth/token/", {"username": "teacher", "password": "wrong"})
        self.assertEqual(LoginAttempt.objects.count(), 1)
        self.sign_in_api(self.teacher)
        self.assertEqual(LoginAttempt.objects.count(), 0)

    def test_refresh_rotates_and_the_old_refresh_token_stops_working(self):
        tokens = self.sign_in_api(self.teacher)
        response = self.client.post("/api/v1/auth/token/refresh/", {"refresh": tokens["refresh"]})
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.json()["refresh"], tokens["refresh"])
        reused = self.client.post("/api/v1/auth/token/refresh/", {"refresh": tokens["refresh"]})
        self.assertEqual(reused.status_code, 401)

    def test_logout_blacklists_the_refresh_token(self):
        tokens = self.sign_in_api(self.teacher)
        self.assertEqual(
            self.client.post("/api/v1/auth/logout/", {"refresh": tokens["refresh"]}).status_code,
            200,
        )
        response = self.client.post("/api/v1/auth/token/refresh/", {"refresh": tokens["refresh"]})
        self.assertEqual(response.status_code, 401)

    def test_deactivation_revokes_existing_tokens(self):
        tokens = self.sign_in_api(self.teacher)
        toggle_access(self.admin, self.teacher)
        self.bearer(tokens["access"])
        self.assertEqual(self.client.get("/api/v1/me/").status_code, 401)
        self.client.credentials()
        response = self.client.post("/api/v1/auth/token/refresh/", {"refresh": tokens["refresh"]})
        self.assertEqual(response.status_code, 401)

    def test_requests_without_a_token_are_401(self):
        response = self.client.get("/api/v1/me/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "not_authenticated")
        self.assertEqual(response["Cache-Control"], "no-store, private")


class PasswordChangeTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.teacher.must_change_password = True
        self.teacher.save()
        self.tokens = self.sign_in_api(self.teacher)
        self.bearer(self.tokens["access"])

    def change(self, current, new):
        return self.client.post(
            "/api/v1/me/password/", {"current_password": current, "new_password": new}
        )

    def test_profile_is_reachable_before_the_change(self):
        self.assertTrue(self.tokens["must_change_password"])
        self.assertTrue(self.client.get("/api/v1/me/").json()["must_change_password"])

    def test_wrong_current_password_and_weak_new_password_name_the_field(self):
        wrong = self.change("wrong", NEW_PASSWORD)
        self.assertEqual(wrong.status_code, 400)
        self.assertIn("current_password", wrong.json()["fields"])
        weak = self.change(PASSWORD, "short")
        self.assertEqual(weak.status_code, 400)
        self.assertIn("new_password", weak.json()["fields"])

    def test_change_revokes_old_tokens_and_returns_new_ones(self):
        response = self.change(PASSWORD, NEW_PASSWORD)
        self.assertEqual(response.status_code, 200)
        self.teacher.refresh_from_db()
        self.assertFalse(self.teacher.must_change_password)
        self.assertTrue(AuditEvent.objects.filter(action="account.password_changed").exists())

        old = self.client.get("/api/v1/me/")  # still sending the old access token
        self.assertEqual(old.status_code, 401)
        self.assertEqual(old.json()["code"], "password_changed")

        self.bearer(response.json()["access"])
        self.assertEqual(self.client.get("/api/v1/me/").status_code, 200)


class DocsTests(ApiTestCase):
    def test_schema_and_docs_pages_are_public_and_self_hosted(self):
        schema = self.client.get("/api/schema/?format=json")
        self.assertEqual(schema.status_code, 200)
        self.assertEqual(schema.json()["info"]["title"], "EduNexa API")

        for url in ("/api/docs/", "/api/redoc/"):
            with self.subTest(url=url):
                page = self.client.get(url)
                self.assertEqual(page.status_code, 200)
                html = page.content.decode()
                self.assertNotIn("<script>", html)  # no inline script: the CSP stays strict
                self.assertNotIn("https://", html)  # nothing loaded from a CDN
                self.assertIn("script-src 'self'", page["Content-Security-Policy"])
        script = self.client.get("/api/docs/?script=")
        self.assertEqual(script.status_code, 200)
        self.assertIn("SwaggerUIBundle", script.content.decode())
