"""A register or mark sheet is saved in a fixed number of queries, however big the class:
rows are written in bulk after every row has been checked."""

from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import User
from apps.attendance.models import Attendance
from apps.attendance.services import save_register
from apps.core.testing import SchoolTestCase
from apps.exams.models import Exam, Mark
from apps.exams.services import save_marks
from apps.students.models import Enrollment, Student


class BulkSaveTests(SchoolTestCase):
    def add_students(self, count):
        for n in range(count):
            user = User.objects.create_user(
                f"extra{n}",
                f"extra{n}@example.com",
                role=User.Role.STUDENT,
                branch=self.a,
                must_change_password=False,
            )
            Enrollment.objects.create(
                student=Student.objects.create(user=user, admission_number=f"EXTRA{n}"),
                classroom=self.c,
                year=self.year,
                joined_on=self.today,
            )

    def everyone(self, value):
        return {pk: value for pk in self.c.enrollments.values_list("pk", flat=True)}

    def queries(self, action):
        with CaptureQueriesContext(connection) as captured:
            action()
        return len(captured)

    def test_a_register_costs_the_same_queries_for_any_class_size(self):
        day = self.today - timedelta(days=1)
        small = self.queries(
            lambda: save_register(self.teacher, self.c, day, self.everyone("P"), 0)
        )
        self.add_students(10)
        bigger = self.queries(
            lambda: save_register(self.teacher, self.c, self.today, self.everyone("P"), 0)
        )
        self.assertEqual(bigger, small)
        # A correction writes only what changed, and keeps the other rows.
        statuses = self.everyone("P") | {self.e1.pk: "A"}
        save_register(self.teacher, self.c, self.today, statuses, 1, "Alice was absent")
        rows = dict(
            Attendance.objects.filter(session__date=self.today).values_list("enrollment", "status")
        )
        self.assertEqual(rows, statuses)

    def test_a_mark_sheet_costs_the_same_queries_for_any_class_size(self):
        small = self.queries(
            lambda: save_marks(
                self.teacher, self.exam, self.everyone((Decimal("40"), False)), self.exam.version
            )
        )
        self.add_students(10)
        exam = Exam.objects.create(
            classroom=self.c,
            subject=self.math,
            title="Unit test",
            date=self.today,
            max_marks=100,
            pass_marks=35,
        )
        bigger = self.queries(
            lambda: save_marks(
                self.teacher, exam, self.everyone((Decimal("40"), False)), exam.version
            )
        )
        self.assertEqual(bigger, small)
        # Change one, clear one, keep the rest.
        entries = self.everyone((Decimal("40"), False)) | {
            self.e1.pk: (None, True),
            self.e2.pk: (None, False),
        }
        exam.refresh_from_db()
        save_marks(self.teacher, exam, entries, exam.version)
        marks = {m.enrollment_id: (m.score, m.absent) for m in Mark.objects.filter(exam=exam)}
        self.assertEqual(marks.pop(self.e1.pk), (None, True))
        self.assertNotIn(self.e2.pk, marks)
        self.assertEqual(set(marks.values()), {(Decimal("40.00"), False)})
