from django.urls import reverse

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.core.testing import PASSWORD, SchoolTestCase
from apps.students.models import Enrollment, Student


class AdmissionTests(SchoolTestCase):
    """Adding a student creates the login, profile and enrollment together."""

    def admission(self, **overrides):
        data = {
            "username": "newstudent",
            "first_name": "Nila",
            "last_name": "Varma",
            "email": "newstudent@example.com",
            "password": PASSWORD,
            "role": "student",
            "branch": self.a.pk,
            "admission_number": "NEW-001",
            "classroom": self.c.pk,
            "joined_on": self.today.isoformat(),
        }
        return {**data, **overrides}

    def test_admin_admits_student_with_enrollment_and_audit(self):
        self.sign_in(self.admin)
        response = self.client.post(reverse("student_create"), self.admission())
        self.assertRedirects(response, reverse("students"), fetch_redirect_response=False)
        user = User.objects.get(username="newstudent")
        self.assertEqual(user.role, User.Role.STUDENT)
        self.assertTrue(user.must_change_password)
        self.assertTrue(user.check_password(PASSWORD))
        student = Student.objects.get(user=user, admission_number="NEW-001")
        enrollment = Enrollment.objects.get(student=student)
        self.assertEqual((enrollment.classroom, enrollment.year), (self.c, self.year))
        event = AuditEvent.objects.get(action="account.created", target="newstudent")
        self.assertEqual(event.details, {"role": "student"})

    def test_duplicate_admission_number_creates_nothing(self):
        self.sign_in(self.admin)
        response = self.client.post(
            reverse("student_create"), self.admission(admission_number="ALICE")
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This admission number is already in use.")
        self.assertFalse(User.objects.filter(username="newstudent").exists())

    def test_classroom_from_another_branch_is_rejected(self):
        self.sign_in(self.root)
        response = self.client.post(
            reverse("student_create"), self.admission(classroom=self.foreign_class.pk)
        )
        self.assertContains(response, "Choose a classroom in the selected branch.")
        self.assertFalse(User.objects.filter(username="newstudent").exists())
