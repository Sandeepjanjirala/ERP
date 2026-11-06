"""Admitting and enrolling students over the API: one transaction, the same rules as the web."""

from datetime import timedelta

from apps.academics.models import AcademicYear, Classroom
from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.core.testing import PASSWORD, ApiTestCase
from apps.students.models import Enrollment, Student


class AdmissionTests(ApiTestCase):
    def body(self, **overrides):
        return {
            "username": "dana",
            "first_name": "Dana",
            "last_name": "Iyer",
            "email": "dana@example.com",
            "password": PASSWORD,
            "admission_number": "GF-0099",
            "classroom": self.c.pk,
            "joined_on": self.today.isoformat(),
            **overrides,
        }

    def test_admin_admits_a_student(self):
        self.as_user(self.admin)
        response = self.client.post("/api/v1/students/", self.body())
        self.assertEqual(response.status_code, 201, response.content)
        student = Student.objects.get(admission_number="GF-0099")
        self.assertEqual(student.user.role, User.Role.STUDENT)
        self.assertEqual(student.user.branch, self.a)  # the classroom's branch
        self.assertTrue(student.user.must_change_password)
        self.assertEqual(response.json()["enrollments"][0]["classroom"]["id"], self.c.pk)

    def test_admission_rules(self):
        cases = [
            (self.admin, {"classroom": self.foreign_class.pk}, 400, "classroom"),
            (self.admin, {"admission_number": "ALICE"}, 400, "admission_number"),
            (self.admin, {"username": "Alice"}, 400, "username"),
            (
                self.admin,
                {"joined_on": (self.year.ends_on + timedelta(days=1)).isoformat()},
                400,
                None,
            ),
            (self.admin, {"password": "short"}, 400, None),
            (self.principal, {}, 403, None),
            (self.teacher, {}, 403, None),
        ]
        for actor, changes, status, field in cases:
            with self.subTest(actor=actor.username, changes=changes):
                self.as_user(actor)
                response = self.client.post("/api/v1/students/", self.body(**changes))
                self.assertEqual(response.status_code, status, response.content)
                if field:
                    self.assertIn(field, response.json()["fields"])

    def test_a_failed_admission_leaves_nothing_behind(self):
        """The login is created first; if the enrollment fails, the transaction removes it."""
        self.as_user(self.admin)
        late = (self.year.ends_on + timedelta(days=1)).isoformat()
        self.assertEqual(
            self.client.post("/api/v1/students/", self.body(joined_on=late)).status_code, 400
        )
        self.assertFalse(User.objects.filter(username="dana").exists())
        self.assertFalse(Student.objects.filter(admission_number="GF-0099").exists())


class EnrollmentTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        # Next year's class, for moving Alice up.
        self.next_year = AcademicYear.objects.create(
            name="Next year",
            starts_on=self.year.ends_on + timedelta(days=1),
            ends_on=self.year.ends_on + timedelta(days=300),
        )
        self.next_class = Classroom.objects.create(
            branch=self.a, year=self.next_year, grade="10", section="A"
        )

    def test_list_is_scoped(self):
        self.as_user(self.teacher)
        rows = self.client.get("/api/v1/enrollments/").json()["results"]
        self.assertEqual(sorted(r["id"] for r in rows), sorted([self.e1.pk, self.e2.pk]))
        self.as_user(self.e1.student.user)
        self.assertEqual(self.client.get("/api/v1/enrollments/").status_code, 403)

    def test_enroll_for_next_year(self):
        self.as_user(self.admin)
        response = self.client.post(
            "/api/v1/enrollments/",
            {
                "student": self.e1.student.pk,
                "classroom": self.next_class.pk,
                "joined_on": self.next_year.starts_on.isoformat(),
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["year"]["id"], self.next_year.pk)
        self.assertTrue(AuditEvent.objects.filter(action="setup.enrollment.saved").exists())

    def test_enrollment_rules(self):
        same_year = {"student": self.e1.student.pk, "classroom": self.c.pk}
        same_year["joined_on"] = self.today.isoformat()
        cases = [
            (self.admin, same_year, 400),  # already enrolled this year
            (
                self.admin,
                {**same_year, "student": self.foreign_enrollment.student.pk},
                400,  # another branch's student: not a valid choice
            ),
            (self.principal, same_year, 403),
        ]
        for actor, body, status in cases:
            with self.subTest(actor=actor.username, body=body):
                self.as_user(actor)
                self.assertEqual(self.client.post("/api/v1/enrollments/", body).status_code, status)
        self.assertEqual(Enrollment.objects.filter(student=self.e1.student).count(), 1)
