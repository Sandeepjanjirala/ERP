from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.accounts.models import User
from apps.attendance.services import save_register
from apps.core.testing import PASSWORD, SchoolTestCase
from apps.students.models import Enrollment, Student


class StudentTests(SchoolTestCase):
    """Student visibility and enrollment rules."""

    def test_branch_student_query_isolation(self):
        self.sign_in(self.admin)
        response = self.client.get(reverse("students"))
        self.assertContains(response, "alice")
        self.assertNotContains(response, "charlie")
        self.assertEqual(
            self.client.get(
                reverse("student_report", args=[self.foreign_enrollment.student_id])
            ).status_code,
            404,
        )

    def test_student_cannot_browse_peers_or_staff(self):
        self.sign_in(self.e1.student.user)
        for url in ["/students/", "/users/", "/setup/", "/attendance/", "/reports/", "/activity/"]:
            self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(
            self.client.get(reverse("student_report", args=[self.e2.student_id])).status_code, 404
        )

    def test_retroactive_enrollment_after_recording_rejected(self):
        save_register(self.teacher, self.c, self.today, {self.e1.pk: "P", self.e2.pk: "P"}, 0)
        user = User.objects.create_user(
            "latejoin", "latejoin@example.com", PASSWORD, role="student", branch=self.a
        )
        student = Student.objects.create(user=user, admission_number="LATE")
        with self.assertRaises(ValidationError):
            Enrollment.objects.create(
                student=student, classroom=self.c, year=self.year, joined_on=self.today
            )

    def test_no_duplicate_enrollment_same_year(self):
        with self.assertRaises(ValidationError):
            Enrollment.objects.create(
                student=self.e1.student, classroom=self.c, year=self.year, joined_on=self.today
            )
