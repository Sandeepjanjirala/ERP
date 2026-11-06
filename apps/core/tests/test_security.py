from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

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
    def policy(self, csp_extra=None):
        def view(request):
            response = HttpResponse()
            if csp_extra:
                response.csp_extra = csp_extra
            return response

        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        return SecurityHeadersMiddleware(view)(request)["Content-Security-Policy"]

    def test_only_the_redoc_page_allows_blob_workers(self):
        self.assertIn(
            "worker-src 'self' blob:", self.client.get("/api/redoc/")["Content-Security-Policy"]
        )
        for url in ("/api/docs/", "/accounts/login/"):
            with self.subTest(url=url):
                self.assertNotIn("worker-src", self.client.get(url)["Content-Security-Policy"])

    def test_an_addition_comes_after_the_base_policy(self):
        """Browsers keep the first copy of a directive, so "script-src *" here changes nothing."""
        policy = self.policy("script-src *")
        self.assertTrue(policy.startswith(SecurityHeadersMiddleware.CONTENT_SECURITY_POLICY))
        self.assertLess(policy.index("script-src 'self'"), policy.index("script-src *"))
        self.assertEqual(self.policy(), SecurityHeadersMiddleware.CONTENT_SECURITY_POLICY)
