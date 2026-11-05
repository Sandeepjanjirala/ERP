from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from apps.academics.selectors import classrooms
from apps.core.exceptions import Conflict
from apps.core.testing import SchoolTestCase
from apps.exams.models import Mark
from apps.exams.selectors import exams
from apps.exams.services import save_marks, transition_exam


class ResultWorkflowTests(SchoolTestCase):
    """Marks and the Draft -> Submitted -> Published workflow."""

    def test_teacher_cannot_view_foreign_exam_or_roster(self):
        self.sign_in(self.teacher)
        self.assertEqual(
            self.client.get(reverse("exam_detail", args=[self.foreign_exam.pk])).status_code, 404
        )
        self.assertNotIn(self.foreign_class, list(classrooms(self.teacher)))

    def test_teacher_subject_permissions_on_save(self):
        with self.assertRaises(PermissionDenied):
            save_marks(
                self.teacher,
                self.science_exam,
                {self.e1.pk: (Decimal("30"), False), self.e2.pk: (Decimal("40"), False)},
                1,
            )

    def test_invalid_marks_rollback_whole_save(self):
        with self.assertRaises(ValidationError):
            save_marks(
                self.teacher,
                self.exam,
                {self.e1.pk: (Decimal("80"), False), self.e2.pk: (Decimal("101"), False)},
                1,
            )
        self.assertEqual(Mark.objects.count(), 0)
        self.exam.refresh_from_db()
        self.assertEqual(self.exam.version, 1)

    def test_negative_marks_and_absent_with_score_rejected(self):
        for entry in [(Decimal("-1"), False), (Decimal("0"), True)]:
            with self.subTest(entry=entry):
                with self.assertRaises(ValidationError):
                    save_marks(
                        self.teacher,
                        self.exam,
                        {self.e1.pk: entry, self.e2.pk: (Decimal("10"), False)},
                        1,
                    )

    def test_stale_mark_save_is_rejected(self):
        self.fill()
        with self.assertRaises(Conflict):
            save_marks(
                self.teacher,
                self.exam,
                {self.e1.pk: (Decimal("20"), False), self.e2.pk: (Decimal("20"), False)},
                1,
            )

    def test_cannot_submit_incomplete_marks(self):
        with self.assertRaises(ValidationError):
            transition_exam(self.teacher, self.exam, "submit", 1)

    def test_teacher_cannot_publish(self):
        exam = self.fill()
        transition_exam(self.teacher, exam, "submit", exam.version)
        exam.refresh_from_db()
        with self.assertRaises(PermissionDenied):
            transition_exam(self.teacher, exam, "publish", exam.version)

    def test_submitted_marks_locked(self):
        exam = self.fill()
        transition_exam(self.teacher, exam, "submit", exam.version)
        exam.refresh_from_db()
        with self.assertRaises(ValidationError):
            save_marks(
                self.teacher,
                exam,
                {self.e1.pk: (Decimal("90"), False), self.e2.pk: (Decimal("90"), False)},
                exam.version,
            )

    def test_student_cannot_see_draft_data(self):
        self.fill()
        self.sign_in(self.e1.student.user)
        response = self.client.get(reverse("student_report", args=[self.e1.student_id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["summary"]["count"], 0)
        self.assertEqual(
            self.client.get(reverse("exam_detail", args=[self.exam.pk])).status_code, 404
        )

    def test_published_report_contains_only_self(self):
        self.publish()
        self.sign_in(self.e1.student.user)
        response = self.client.get(reverse("student_report", args=[self.e1.student_id]))
        self.assertEqual(response.context["summary"]["percentage"], Decimal("80.0"))
        self.assertNotContains(response, "bob")
        self.assertEqual(len(response.context["marks"]), 1)

    def test_reopen_hides_results_until_republished(self):
        exam = self.publish()
        transition_exam(self.principal, exam, "reopen", exam.version, "Correction requested")
        self.assertFalse(exams(self.e1.student.user).exists())

    def test_teacher_report_subject_scope(self):
        self.publish()
        self.assertNotIn(self.exam.pk, exams(self.other_teacher).values_list("pk", flat=True))

    def test_bad_transition_renders_validation_error(self):
        self.sign_in(self.teacher)
        response = self.client.post(
            reverse("exam_detail", args=[self.exam.pk]), {"action": "submit", "version": 1}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "every enrolled student")

    def test_absent_zero_is_not_a_pass_even_when_pass_threshold_zero(self):
        self.exam.pass_marks = 0
        self.exam.save()
        mark = Mark.objects.create(exam=self.exam, enrollment=self.e1, absent=True)
        self.assertFalse(mark.passed)
        self.assertEqual(mark.percentage, 0)
