from datetime import timedelta

from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import LoginAttempt
from apps.accounts.tasks import flush_expired_tokens
from apps.accounts.throttling import throttle
from apps.core.middleware import SecurityHeadersMiddleware
from apps.core.testing import SchoolTestCase


class SecurityTests(SchoolTestCase):
    """CSRF, security headers, and every page rendering for every role."""

    def test_csrf_blocks_writes(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.teacher)
        self.assertEqual(
            client.post(
                reverse("exam_detail", args=[self.exam.pk]), {"action": "save"}
            ).status_code,
            403,
        )

    def test_security_headers_and_no_store(self):
        self.sign_in(self.admin)
        response = self.client.get("/")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])

    def test_pages_render_for_each_role(self):
        paths = [
            "/",
            "/students/",
            "/exams/",
            "/reports/",
            "/attendance/",
            "/setup/",
            "/users/",
            "/activity/",
        ]
        for actor in [self.root, self.admin, self.principal, self.teacher, self.e1.student.user]:
            self.sign_in(actor)
            for path in paths:
                with self.subTest(actor=actor.role, path=path):
                    response = self.client.get(path)
                    self.assertIn(response.status_code, [200, 302, 403])
        self.sign_in(self.teacher)
        for path in [
            reverse("exam_detail", args=[self.exam.pk]),
            reverse("attendance") + f"?classroom={self.c.pk}&date={self.today.isoformat()}",
            reverse("student_report", args=[self.e1.student_id]),
        ]:
            self.assertEqual(self.client.get(path).status_code, 200)


class ContentSecurityPolicyTests(TestCase):
    BASE = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; "
        "img-src 'self' data:; object-src 'none'; base-uri 'self'; form-action 'self'; "
        "frame-ancestors 'none'"
    )

    def policy(self, csp_add=None):
        def view(request):
            response = HttpResponse()
            if csp_add:
                response.csp_add = csp_add
            return response

        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        return SecurityHeadersMiddleware(view)(request)["Content-Security-Policy"]

    def directives(self, policy):
        return dict(part.split(" ", 1) for part in policy.split("; "))

    def test_the_base_policy(self):
        self.assertEqual(self.policy(), self.BASE)

    def test_only_the_redoc_page_allows_blob_workers(self):
        self.assertIn(
            "worker-src 'self' blob:", self.client.get("/api/redoc/")["Content-Security-Policy"]
        )
        for url in ("/api/docs/", "/accounts/login/"):
            with self.subTest(url=url):
                self.assertNotIn("worker-src", self.client.get(url)["Content-Security-Policy"])

    def test_a_page_adds_sources_to_a_directive_once(self):
        """One script-src with both sources: a second copy would be ignored by browsers."""
        policy = self.policy({"script-src": ["https://checkout.example", "'self'"]})
        self.assertEqual(policy.count("script-src"), 1)
        directives = self.directives(policy)
        self.assertEqual(directives["script-src"], "'self' https://checkout.example")
        self.assertEqual(directives["default-src"], "'self'")
        self.assertEqual(self.policy(), self.BASE)  # the next page is back to the base policy

    def test_a_new_directive_starts_from_default_src(self):
        directives = self.directives(self.policy({"frame-src": ["https://pay.example"]}))
        self.assertEqual(directives["frame-src"], "'self' https://pay.example")

    def test_none_directives_cannot_be_opened(self):
        for name in ("object-src", "frame-ancestors"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.policy({name: ["*"]})


class SignInCounterCleanupTests(TestCase):
    def test_the_nightly_job_drops_old_sign_in_counters(self):
        throttle("portal-login", "made-up-user-1")
        throttle("portal-login", "made-up-user-2")
        LoginAttempt.objects.filter(pk=throttle("portal-login", "made-up-user-1")[1]).update(
            started_at=timezone.now() - timedelta(days=2)
        )
        flush_expired_tokens()
        self.assertEqual(LoginAttempt.objects.count(), 1)  # the recent one still limits
