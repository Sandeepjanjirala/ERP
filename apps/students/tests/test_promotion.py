"""Year-end promotion: transactional, safe to run twice, for principals and admins only."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest import skipUnless

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase
from django.urls import reverse

from apps.academics.models import AcademicYear, Classroom, Grade
from apps.academics.services import default_terms
from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.core.testing import ApiTestCase, SchoolTestCase
from apps.students.models import Enrollment
from apps.students.services import promote_class, promotion_preview


def next_year_fixture(case):
    """Next year, with Class 10-A (moving up) and 9-A again (repeating), in North."""
    case.next_year = AcademicYear.objects.create(
        name="Next year",
        starts_on=case.year.ends_on + timedelta(days=1),
        ends_on=case.year.ends_on + timedelta(days=300),
    )
    default_terms(case.next_year)
    case.grade10 = Grade.objects.create(branch=case.a, name="10", order=10)
    case.up = Classroom.objects.create(
        branch=case.a, year=case.next_year, grade=case.grade10, section="A"
    )
    case.again = Classroom.objects.create(
        branch=case.a, year=case.next_year, grade=case.grade9, section="A"
    )


class PromotionTests(ApiTestCase):
    def setUp(self):
        next_year_fixture(self)

    def new_enrollments(self):
        return dict(
            Enrollment.objects.filter(year=self.next_year).values_list("student_id", "classroom_id")
        )

    def everyone(self, choice="promote"):
        return {self.e1.pk: choice, self.e2.pk: choice}

    def test_every_student_needs_a_decision(self):
        with self.assertRaisesMessage(ValidationError, "has no decision"):
            promote_class(self.principal, self.c, {self.e1.pk: "promote"}, self.up)
        self.assertFalse(Enrollment.objects.filter(year=self.next_year).exists())

    def test_everyone_moves_up(self):
        rows = promotion_preview(self.c)
        self.assertEqual([row["default"] for row in rows], ["promote", "promote"])
        counts = promote_class(self.principal, self.c, self.everyone(), self.up)
        self.assertEqual((counts["promote"], counts["already_moved"]), (2, 0))
        self.assertEqual(
            self.new_enrollments(), {self.e1.student_id: self.up.pk, self.e2.student_id: self.up.pk}
        )
        for old in (self.e1, self.e2):
            old.refresh_from_db()
            self.assertEqual(old.left_on, self.year.ends_on)  # closed on the last day of the year
        new = Enrollment.objects.get(student=self.e1.student, year=self.next_year)
        self.assertEqual(new.joined_on, self.next_year.starts_on)
        event = AuditEvent.objects.get(action="students.promoted")
        self.assertEqual(event.details["promote"], 2)

    def test_repeat_and_leave(self):
        decisions = {self.e1.pk: "repeat", self.e2.pk: "leave"}
        with self.assertRaisesMessage(
            ValidationError, "Choose a class for the students who repeat"
        ):
            promote_class(self.principal, self.c, decisions, self.up)
        self.e1.refresh_from_db()
        self.assertIsNone(self.e1.left_on)  # all or nothing: the first student wasn't touched
        counts = promote_class(self.principal, self.c, decisions, self.up, self.again)
        self.assertEqual((counts["repeat"], counts["leave"]), (1, 1))
        self.assertEqual(self.new_enrollments(), {self.e1.student_id: self.again.pk})

    def test_running_it_again_changes_nothing(self):
        promote_class(self.principal, self.c, self.everyone(), self.up)
        counts = promote_class(self.principal, self.c, {self.e1.pk: "leave"}, self.up)
        self.assertEqual(counts, {"promote": 0, "repeat": 0, "leave": 0, "already_moved": 2})
        self.assertEqual(Enrollment.objects.filter(year=self.next_year).count(), 2)
        self.assertTrue(all(row["already_moved"] for row in promotion_preview(self.c)))

    def test_the_classes_must_make_sense(self):
        same_year = Classroom.objects.create(
            branch=self.a, year=self.year, grade=self.grade10, section="Z"
        )
        south = Classroom.objects.create(
            branch=self.b, year=self.next_year, grade=self.foreign_grade9, section="Q"
        )
        cases = {
            "same year": (same_year, None, "starts after Test year"),
            "not a higher grade": (self.again, None, "choose a grade above 9"),
            "other branch": (south, None, "same branch"),
            "repeat in another grade": (self.up, self.up, "need a 9 class"),
        }
        for case, (target, repeat, message) in cases.items():
            with self.subTest(case=case), self.assertRaisesMessage(ValidationError, message):
                promote_class(self.admin, self.c, self.everyone(), target, repeat)
        with self.assertRaisesMessage(ValidationError, "student of this class"):
            promote_class(self.admin, self.c, {self.foreign_enrollment.pk: "promote"}, self.up)

    def test_after_the_last_grade_students_leave(self):
        """Grade 10 is North's last grade: its students leave, and no class is needed for that."""
        last = Classroom.objects.create(
            branch=self.a, year=self.year, grade=self.grade10, section="B"
        )
        Enrollment.objects.filter(pk=self.e2.pk).update(classroom=last)
        self.assertEqual([row["default"] for row in promotion_preview(last)], ["leave"])
        with self.assertRaisesMessage(ValidationError, "is the last grade"):
            promote_class(self.admin, last, {self.e2.pk: "promote"})
        counts = promote_class(self.admin, last, {self.e2.pk: "leave"})
        self.assertEqual(counts["leave"], 1)
        self.e2.refresh_from_db()
        self.assertEqual(self.e2.left_on, self.year.ends_on)
        with self.assertRaisesMessage(ValidationError, "Choose the class the students move up to"):
            promote_class(self.admin, self.c, {self.e1.pk: "promote"})  # Bob is in 10-B now

    def test_only_principals_and_admins_of_the_branch(self):
        for user in (self.teacher, self.accountant, self.foreign_teacher):
            with self.subTest(user=user.username), self.assertRaises(PermissionDenied):
                promote_class(user, self.c, self.everyone(), self.up)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse("promotion")).status_code, 403)

    def test_page_and_api(self):
        self.client.force_login(self.principal)
        url = (
            reverse("promotion") + f"?source={self.c.pk}&target={self.up.pk}&repeat={self.again.pk}"
        )
        page = self.client.get(url)
        self.assertEqual(len(page.context["rows"]), 2)
        done = self.client.post(
            url,
            {f"decision_{self.e1.pk}": "promote", f"decision_{self.e2.pk}": "repeat"},
            follow=True,
            format="multipart",
        )
        self.assertContains(done, "1 moved up, 1 repeat, 0 left.")
        self.as_user(self.admin)
        api = f"/api/v1/classrooms/{self.c.pk}/promotion/"
        preview = self.client.get(api).json()
        self.assertTrue(all(row["already_moved"] for row in preview))
        again = self.client.post(
            api, {"target": self.up.pk, "decisions": {self.e1.pk: "leave"}}, format="json"
        ).json()
        self.assertEqual(again["already_moved"], 2)
        self.as_user(self.teacher)
        self.assertEqual(self.client.get(api).status_code, 403)


@skipUnless(connection.vendor == "postgresql", "Needs PostgreSQL row locks and real threads.")
class PromotionRaceTests(TransactionTestCase):
    def setUp(self):
        SchoolTestCase.setUpTestData.__func__(type(self))
        next_year_fixture(self)

    def test_two_leaders_promoting_at_once_move_each_student_once(self):
        barrier = Barrier(2)

        def run(user_pk):
            close_old_connections()
            try:
                actor = User.objects.get(pk=user_pk)
                barrier.wait(timeout=10)
                return promote_class(
                    actor, self.c, {self.e1.pk: "promote", self.e2.pk: "promote"}, self.up
                )
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, [self.principal.pk, self.admin.pk], timeout=60))
        self.assertEqual(sorted(r["promote"] for r in results), [0, 2])
        self.assertEqual(sorted(r["already_moved"] for r in results), [0, 2])
        self.assertEqual(Enrollment.objects.filter(year=self.next_year).count(), 2)
