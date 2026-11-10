"""The API's access matrix: every endpoint, every role, in one table.

Reads show the status each role gets. Writes are sent with an empty body: 400 means the caller
got past the permission checks (and the empty body then failed validation); 403 means the role
may not use the endpoint at all. Record-level rules (which classroom, which exam) are tested
per endpoint in each app's test_api_*.py.
"""

from datetime import timedelta

from apps.core.testing import ApiTestCase
from apps.fees.models import FeeHead, FeePlan
from apps.fees.services import issue_invoices, record_counter_payment, save_fee_plan

ROLES = ("root", "admin", "principal", "teacher", "student", "parent", "accountant")
ALL, ACADEMIC, STAFF, LEADERS, MANAGERS = (
    (200, 200, 200, 200, 200, 200, 200),
    (200, 200, 200, 200, 200, 200, 403),  # everyone but accountants: marks, attendance, reports
    (200, 200, 200, 200, 403, 403, 403),
    (200, 200, 200, 403, 403, 403, 403),
    (200, 200, 403, 403, 403, 403, 403),
)
FEES = (200, 200, 403, 403, 403, 200, 200)  # finance staff, and parents for their children
FINANCE = (200, 200, 403, 403, 403, 403, 200)
# For writes with an empty body.
WRITE_MANAGERS = (400, 400, 403, 403, 403, 403, 403)
WRITE_FINANCE = (400, 400, 403, 403, 403, 403, 400)


class ApiPermissionMatrixTests(ApiTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Alice's invoice, part paid, so the fee endpoints have a record to act on.
        head = FeeHead.objects.create(branch=cls.a, name="Tuition", code="tuition")
        cls.plan = save_fee_plan(
            cls.admin, FeePlan(branch=cls.a, year=cls.year, grade=cls.grade9), {head: 100000}
        )
        created, _ = issue_invoices(cls.admin, cls.plan, "Term 1", cls.today + timedelta(days=30))
        cls.invoice = next(i for i in created if i.student_id == cls.e1.student_id)
        cls.receipt = record_counter_payment(cls.admin, cls.invoice, 1000, "cash").receipt

    def users(self):
        return {
            "root": self.root,
            "admin": self.admin,
            "principal": self.principal,
            "teacher": self.teacher,
            "student": self.e1.student.user,
            "parent": self.parent,  # Alice's mother
            "accountant": self.accountant,
        }

    def reads(self):
        return [
            ("/api/v1/me/", ALL),
            ("/api/v1/organization/", ALL),
            ("/api/v1/branches/", ALL),
            ("/api/v1/years/", ALL),
            ("/api/v1/grades/", ALL),
            ("/api/v1/terms/", ALL),
            (f"/api/v1/years/{self.year.pk}/terms/", ALL),
            ("/api/v1/classrooms/", ALL),
            ("/api/v1/exams/", ACADEMIC),
            ("/api/v1/grading-scales/", ACADEMIC),
            ("/api/v1/periods/", ACADEMIC),
            (f"/api/v1/classrooms/{self.c.pk}/timetable/", ACADEMIC),
            ("/api/v1/timetable/mine/", (403, 403, 403, 200, 403, 403, 403)),
            ("/api/v1/announcements/", ALL),
            ("/api/v1/leave-requests/", ACADEMIC),
            ("/api/v1/notifications/", ALL),
            ("/api/v1/notifications/unread-count/", ALL),
            (f"/api/v1/students/{self.e1.student.pk}/report/", ACADEMIC),
            (f"/api/v1/students/{self.e1.student.pk}/report-card/", ACADEMIC),
            ("/api/v1/subjects/", STAFF),
            ("/api/v1/students/", STAFF),
            ("/api/v1/enrollments/", STAFF),
            ("/api/v1/student-imports/", MANAGERS),
            (f"/api/v1/classrooms/{self.c.pk}/promotion/", LEADERS),
            ("/api/v1/dashboard/", STAFF),
            ("/api/v1/reports/performance/", STAFF),
            ("/api/v1/reports/performance/export/", STAFF),
            (f"/api/v1/classrooms/{self.c.pk}/register/", STAFF),
            (f"/api/v1/exams/{self.exam.pk}/marks/", STAFF),
            ("/api/v1/assignments/", LEADERS),
            ("/api/v1/people/", LEADERS),
            ("/api/v1/activity/", LEADERS),
            ("/api/v1/invoices/", FEES),
            (f"/api/v1/invoices/{self.invoice.pk}/", FEES),
            ("/api/v1/payments/", FEES),
            ("/api/v1/payment-orders/", FEES),
            (f"/api/v1/receipts/{self.receipt.pk}/pdf/", FEES),
            ("/api/v1/fee-heads/", FINANCE),
            ("/api/v1/reports/collections/", FINANCE),
            ("/api/v1/reports/collections/export/", FINANCE),
            ("/api/v1/fee-plans/", FINANCE),
        ]

    def writes(self):
        return [
            ("post", "/api/v1/people/", WRITE_MANAGERS),
            ("post", "/api/v1/students/", WRITE_MANAGERS),
            ("post", "/api/v1/enrollments/", WRITE_MANAGERS),
            ("post", f"/api/v1/enrollments/{self.e1.pk}/leave/", WRITE_MANAGERS),
            # Uploads are multipart only: managers get past the role check, then 415 for JSON.
            ("post", "/api/v1/student-imports/", (415, 415, 403, 403, 403, 403, 403)),
            # Leaders get past the role check; with no class to move up to, the body is refused.
            (
                "post",
                f"/api/v1/classrooms/{self.c.pk}/promotion/",
                (400, 400, 400, 403, 403, 403, 403),
            ),
            ("post", "/api/v1/grades/", WRITE_MANAGERS),
            ("post", "/api/v1/periods/", WRITE_MANAGERS),
            ("post", f"/api/v1/classrooms/{self.c.pk}/timetable/", WRITE_MANAGERS),
            # A year's terms are replaced together, by super admins only.
            ("put", f"/api/v1/years/{self.year.pk}/terms/", (400, 403, 403, 403, 403, 403, 403)),
            ("post", "/api/v1/classrooms/", WRITE_MANAGERS),
            ("post", "/api/v1/subjects/", WRITE_MANAGERS),
            ("post", "/api/v1/assignments/", WRITE_MANAGERS),
            # Branches and years: managers pass the role check, then the setup policy (in the
            # service) refuses branch admins once the body is valid; with an empty body they
            # stop at validation. The policy itself is tested in test_shared_rules.py.
            ("post", "/api/v1/branches/", WRITE_MANAGERS),
            ("post", "/api/v1/years/", WRITE_MANAGERS),
            ("patch", "/api/v1/organization/", (200, 403, 403, 403, 403, 403, 403)),
            ("post", "/api/v1/exams/", (400, 400, 403, 400, 403, 403, 403)),
            # A new version of the grading scale: super admins only.
            ("post", "/api/v1/grading-scales/", (400, 403, 403, 403, 403, 403, 403)),
            ("post", "/api/v1/announcements/", (400, 400, 400, 400, 403, 403, 403)),
            # Only parents apply for leave (for their own children).
            ("post", "/api/v1/leave-requests/", (403, 403, 403, 403, 403, 400, 403)),
            ("post", "/api/v1/notifications/read-all/", (200, 200, 200, 200, 200, 200, 200)),
            (
                "put",
                f"/api/v1/classrooms/{self.c.pk}/register/",
                (400, 400, 400, 400, 403, 403, 403),
            ),
            ("put", f"/api/v1/exams/{self.exam.pk}/marks/", (400, 400, 400, 400, 403, 403, 403)),
            # Families can't see a draft exam at all, so it is a 404 for them.
            ("post", f"/api/v1/exams/{self.exam.pk}/submit/", (400, 400, 400, 400, 404, 404, 403)),
            ("post", f"/api/v1/exams/{self.exam.pk}/publish/", (400, 400, 400, 400, 404, 404, 403)),
            ("post", f"/api/v1/exams/{self.exam.pk}/reopen/", (400, 400, 400, 400, 404, 404, 403)),
            (
                "post",
                f"/api/v1/people/{self.teacher.pk}/toggle-access/",
                (200, 200, 403, 403, 403, 403, 403),
            ),
            ("post", f"/api/v1/invoices/{self.invoice.pk}/payment/", WRITE_FINANCE),
            ("post", f"/api/v1/invoices/{self.invoice.pk}/concession/", WRITE_MANAGERS),
            ("post", f"/api/v1/invoices/{self.invoice.pk}/cancel/", WRITE_MANAGERS),
            ("post", f"/api/v1/fee-plans/{self.plan.pk}/issue/", WRITE_FINANCE),
            ("post", "/api/v1/fee-heads/", WRITE_MANAGERS),
            ("post", "/api/v1/fee-plans/", WRITE_MANAGERS),
            # Only a parent starts an online payment (no body needed: it is the balance).
            (
                "post",
                f"/api/v1/invoices/{self.invoice.pk}/pay-online/",
                (403, 403, 403, 403, 403, 201, 403),
            ),
        ]

    def test_reads(self):
        users = self.users()
        for url, expected in self.reads():
            for role, status in zip(ROLES, expected, strict=True):
                with self.subTest(url=url, role=role):
                    self.as_user(users[role])
                    self.assertEqual(self.client.get(url).status_code, status)

    def test_writes(self):
        users = self.users()
        for method, url, expected in self.writes():
            for role, status in zip(ROLES, expected, strict=True):
                with self.subTest(method=method, url=url, role=role):
                    self.as_user(users[role])
                    response = getattr(self.client, method)(url, {})
                    self.assertEqual(response.status_code, status, response.content)

    def test_anonymous_callers_get_401_everywhere(self):
        self.client.force_authenticate(None)
        for url, _ in self.reads():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 401)
        for method, url, _ in self.writes():
            with self.subTest(method=method, url=url):
                self.assertEqual(getattr(self.client, method)(url, {}).status_code, 401)

    def test_public_endpoints(self):
        """Only sign-in, token refresh, sign-out and the API docs work without a token."""
        self.client.force_authenticate(None)
        for url in ("/api/schema/", "/api/docs/", "/api/redoc/"):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        for url in ("/api/v1/auth/token/", "/api/v1/auth/token/refresh/", "/api/v1/auth/logout/"):
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, {}).status_code, 400)  # needs a body
        # Payment providers call this; only a valid signature makes it do anything.
        self.assertEqual(self.client.post("/api/v1/payments/webhook/sandbox/", {}).status_code, 400)
