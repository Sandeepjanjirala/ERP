from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.academics.models import Classroom, TeachingAssignment
from apps.core.testing import SchoolTestCase
from apps.exams.policies import can_mark


class AcademicSetupTests(SchoolTestCase):
    """Classrooms, subjects and teacher assignments stay inside one branch."""

    def test_branch_assignment_validation(self):
        with self.assertRaises(ValidationError):
            TeachingAssignment.objects.create(
                teacher=self.foreign_teacher, classroom=self.c, subject=self.math
            )
        with self.assertRaises(ValidationError):
            Classroom.objects.create(
                branch=self.a,
                year=self.year,
                grade="8",
                section="A",
                homeroom_teacher=self.foreign_teacher,
            )

    def test_assignment_edit_preserves_class_and_subject(self):
        self.sign_in(self.admin)
        assignment = TeachingAssignment.objects.get(
            teacher=self.teacher, classroom=self.c, subject=self.math
        )
        response = self.client.post(
            reverse("setup_edit", args=["assignment", assignment.pk]),
            {
                "teacher": self.other_teacher.pk,
                "classroom": self.foreign_class.pk,
                "subject": self.foreign_subject.pk,
            },
        )
        self.assertEqual(response.status_code, 302)
        assignment.refresh_from_db()
        self.assertEqual(assignment.teacher_id, self.other_teacher.pk)
        self.assertEqual(assignment.classroom_id, self.c.pk)
        self.assertEqual(assignment.subject_id, self.math.pk)
        self.assertFalse(can_mark(self.teacher, self.exam))
        self.assertTrue(can_mark(self.other_teacher, self.exam))

    def test_setup_form_pages_render(self):
        self.sign_in(self.root)
        for kind in (
            "organization",
            "branch",
            "year",
            "classroom",
            "subject",
            "assignment",
            "enrollment",
        ):
            with self.subTest(kind=kind):
                self.assertEqual(
                    self.client.get(reverse("setup_create", args=[kind])).status_code, 200
                )
