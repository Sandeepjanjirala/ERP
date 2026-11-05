from django.test import Client
from django.urls import reverse

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
