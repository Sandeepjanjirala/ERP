"""The weekly timetable: no class or teacher is ever booked twice in one period."""

from concurrent.futures import ThreadPoolExecutor
from datetime import time
from threading import Barrier
from unittest import skipUnless

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase
from django.urls import reverse

from apps.academics.models import Classroom, Period, TeachingAssignment, TimetableSlot
from apps.academics.services import save_lesson, save_setup_record
from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.core.testing import ApiTestCase, SchoolTestCase

MONDAY, TUESDAY = TimetableSlot.Day.MONDAY, TimetableSlot.Day.TUESDAY


def timetable_fixture(case):
    """Two periods in North, and a second class (9-B) that the maths teacher also teaches."""
    case.p1 = Period.objects.create(
        branch=case.a, number=1, starts_at=time(8, 30), ends_at=time(9, 15)
    )
    case.p2 = Period.objects.create(
        branch=case.a, number=2, starts_at=time(9, 20), ends_at=time(10, 5)
    )
    case.c2 = Classroom.objects.create(
        branch=case.a, year=case.year, grade=case.grade9, section="B"
    )
    case.math_a = TeachingAssignment.objects.get(classroom=case.c, subject=case.math)
    case.science_a = TeachingAssignment.objects.get(classroom=case.c, subject=case.science)
    case.math_b = TeachingAssignment.objects.create(
        teacher=case.teacher, classroom=case.c2, subject=case.math
    )


class TimetableRuleTests(ApiTestCase):
    def setUp(self):
        timetable_fixture(self)

    def test_placing_changing_and_clearing_a_lesson(self):
        slot = save_lesson(self.admin, self.c, MONDAY, self.p1, self.math_a)
        self.assertEqual(
            (slot.subject, slot.teacher, slot.year), (self.math, self.teacher, self.year)
        )
        save_lesson(self.admin, self.c, MONDAY, self.p1, self.science_a)  # same cell, new lesson
        cell = TimetableSlot.objects.get(classroom=self.c, weekday=MONDAY, period=self.p1)
        self.assertEqual(cell.subject, self.science)
        save_lesson(self.admin, self.c, MONDAY, self.p1, None)
        self.assertFalse(TimetableSlot.objects.exists())
        actions = list(
            AuditEvent.objects.filter(action__startswith="timetable.").values_list(
                "action", flat=True
            )
        )
        self.assertEqual(
            sorted(actions), ["timetable.cleared", "timetable.saved", "timetable.saved"]
        )

    def test_a_teacher_is_never_in_two_classes_at_once(self):
        save_lesson(self.admin, self.c, MONDAY, self.p1, self.math_a)
        with self.assertRaisesMessage(
            ValidationError, "teacher already teaches 9-A on Monday in Period 1"
        ):
            save_lesson(self.admin, self.c2, MONDAY, self.p1, self.math_b)
        save_lesson(self.admin, self.c2, TUESDAY, self.p1, self.math_b)  # another day is fine
        save_lesson(self.admin, self.c2, MONDAY, self.p2, self.math_b)  # another period too

    def test_the_database_itself_refuses_double_bookings(self):
        TimetableSlot.objects.create(
            classroom=self.c,
            weekday=MONDAY,
            period=self.p1,
            subject=self.math,
            teacher=self.teacher,
        )
        rows = {
            "class twice": dict(classroom=self.c, subject=self.science, teacher=self.other_teacher),
            "teacher twice": dict(classroom=self.c2, subject=self.math, teacher=self.teacher),
        }  # fmt: skip
        for case, fields in rows.items():
            with self.subTest(case=case), self.assertRaises(IntegrityError), transaction.atomic():
                # bulk_create skips model validation, as a racing request effectively does.
                TimetableSlot.objects.bulk_create(
                    [TimetableSlot(weekday=MONDAY, period=self.p1, year=self.year, **fields)]
                )

    def test_lessons_must_belong_to_the_class_and_branch(self):
        south = Period.objects.create(branch=self.b, number=1, starts_at=time(8), ends_at=time(9))
        cases = {
            "another class's subject": (self.c, MONDAY, self.p1, self.math_b, "taught in this class"),
            "another branch's period": (self.c, MONDAY, south, self.math_a, "period of the classroom's branch"),
            "Sunday": (self.c, 7, self.p1, self.math_a, "Monday to Saturday"),
        }  # fmt: skip
        for case, (classroom, day, period, assignment, message) in cases.items():
            with self.subTest(case=case), self.assertRaisesMessage(ValidationError, message):
                save_lesson(self.admin, classroom, day, period, assignment)

    def test_only_branch_managers_edit_timetables(self):
        for user in (self.teacher, self.principal, self.accountant):
            with self.subTest(user=user.username), self.assertRaises(PermissionDenied):
                save_lesson(user, self.c, MONDAY, self.p1, self.math_a)
        south_admin = User.objects.create_user(
            "southadmin", "sa@x.example", "x", role="admin", branch=self.b
        )
        with self.assertRaises(PermissionDenied):
            save_lesson(south_admin, self.c, MONDAY, self.p1, self.math_a)

    def test_periods_of_a_branch_never_overlap(self):
        with self.assertRaisesMessage(ValidationError, "Periods can't overlap"):
            save_setup_record(
                self.admin,
                "period",
                Period(branch=self.a, number=3, starts_at=time(9), ends_at=time(9, 30)),
            )
        save_setup_record(
            self.root,
            "period",
            Period(branch=self.b, number=1, starts_at=time(9), ends_at=time(9, 30)),
        )  # the same time in another branch is fine


class TimetablePageTests(ApiTestCase):
    def setUp(self):
        timetable_fixture(self)
        save_lesson(self.admin, self.c, MONDAY, self.p1, self.math_a)

    def test_who_sees_what(self):
        url = reverse("classroom_timetable", args=[self.c.pk])
        for user, editable in (
            (self.admin, True),
            (self.teacher, False),
            (self.parent, False),
            (self.e1.student.user, False),
        ):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                page = self.client.get(url)
                self.assertEqual(page.status_code, 200)
                self.assertEqual(page.context["can_edit"], editable)
                self.assertContains(page, "Mathematics")
        self.client.force_login(self.accountant)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.foreign_teacher)
        self.assertEqual(self.client.get(url).status_code, 404)  # another branch's class

    def test_a_cell_shows_the_subject_with_the_teacher_beneath(self):
        """Short options keep six day columns on a desktop page. A class has one teacher per
        subject, so the subject alone identifies the lesson."""
        self.client.force_login(self.admin)
        page = self.client.get(reverse("classroom_timetable", args=[self.c.pk]))
        self.assertContains(page, '">Mathematics</option>')
        self.assertContains(
            page, f'<small class="cell-teacher">{self.teacher.display_name}</small>'
        )

    def test_htmx_saves_one_cell_and_shows_clashes_in_place(self):
        self.client.force_login(self.admin)
        url = reverse("timetable_cell", args=[self.c2.pk])
        clash = {"weekday": MONDAY, "period": self.p1.pk, "assignment": self.math_b.pk}
        response = self.client.post(url, clash, format="multipart", HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)  # htmx swaps in only 2xx responses
        self.assertTemplateUsed(response, "academics/_timetable_cell.html")
        self.assertContains(response, "already teaches 9-A on Monday")
        self.assertFalse(TimetableSlot.objects.filter(classroom=self.c2).exists())
        ok = {**clash, "period": self.p2.pk}
        response = self.client.post(url, ok, format="multipart", HTTP_HX_REQUEST="true")
        self.assertContains(response, "Saved")
        # Without JavaScript the same form posts normally and the page reloads.
        response = self.client.post(url, {**ok, "assignment": ""}, format="multipart")
        self.assertRedirects(response, reverse("classroom_timetable", args=[self.c2.pk]))
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.post(url, ok, format="multipart").status_code, 403)

    def test_a_teachers_week_and_today(self):
        self.client.force_login(self.teacher)
        page = self.client.get(reverse("my_timetable"))
        self.assertEqual(len(page.context["cells"]), 1)
        self.assertContains(page, "9–A")
        dashboard = self.client.get(reverse("dashboard"))
        self.assertIsNotNone(dashboard.context["todays_lessons"])
        self.client.force_login(self.admin)
        self.assertIsNone(self.client.get(reverse("dashboard")).context["todays_lessons"])

    def test_api(self):
        self.as_user(self.parent)
        body = self.client.get(f"/api/v1/classrooms/{self.c.pk}/timetable/").json()
        self.assertEqual([lesson["subject"]["name"] for lesson in body["lessons"]], ["Mathematics"])
        self.assertEqual(len(body["periods"]), 2)
        url = f"/api/v1/classrooms/{self.c2.pk}/timetable/"
        cell = {"weekday": MONDAY, "period": self.p1.pk, "assignment": self.math_b.pk}
        self.assertEqual(self.client.post(url, cell, format="json").status_code, 403)
        self.as_user(self.admin)
        clash = self.client.post(url, cell, format="json")
        self.assertEqual(clash.status_code, 400)
        self.assertIn("already teaches 9-A", clash.json()["detail"])
        saved = self.client.post(url, {**cell, "period": self.p2.pk}, format="json")
        self.assertEqual(len(saved.json()["lessons"]), 1)
        self.as_user(self.teacher)
        mine = self.client.get("/api/v1/timetable/mine/").json()
        self.assertEqual(len(mine), 2)


@skipUnless(connection.vendor == "postgresql", "Needs PostgreSQL row locks and real threads.")
class TimetableRaceTests(TransactionTestCase):
    def setUp(self):
        SchoolTestCase.setUpTestData.__func__(type(self))
        timetable_fixture(self)

    def test_two_admins_booking_one_teacher_at_once(self):
        """Different classes, so no shared lock: the database's unique rule decides."""
        barrier = Barrier(2)
        jobs = [(self.c, self.math_a), (self.c2, self.math_b)]

        def book(job):
            classroom, assignment = job
            close_old_connections()
            try:
                admin = User.objects.get(pk=self.admin.pk)
                barrier.wait(timeout=10)
                save_lesson(admin, classroom, MONDAY, self.p1, assignment)
                return "saved"
            except ValidationError as error:
                return "refused: " + error.messages[0]
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = sorted(pool.map(book, jobs, timeout=60))
        self.assertEqual(results[1], "saved")
        self.assertTrue(
            results[0].startswith("refused: ") and "already teaches" in results[0], results
        )
        self.assertEqual(TimetableSlot.objects.filter(teacher=self.teacher).count(), 1)
