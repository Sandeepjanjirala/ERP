"""Role dashboards: what is waiting for each person, attendance charts, and their cache."""

from datetime import timedelta

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.academics.models import Classroom
from apps.attendance.models import LeaveRequest
from apps.attendance.services import decide_leave, request_leave, save_register
from apps.core.testing import SchoolTestCase
from apps.exams.services import transition_exam
from apps.reports.selectors import attendance_trend, low_attendance, register_version, to_do
from apps.students.services import link_guardian


class StaffDashboardTests(SchoolTestCase):
    def test_whats_waiting_for_each_role(self):
        exam = self.fill()
        self.assertEqual([e.title for e in to_do(self.teacher)["drafts"]], ["Midterm"])
        self.assertEqual(to_do(self.other_teacher)["drafts"], [self.science_exam])
        self.assertEqual(to_do(self.principal)["drafts"], [])  # principals don't enter marks
        transition_exam(self.teacher, exam, "submit", exam.version)
        self.assertEqual([e.title for e in to_do(self.principal)["awaiting"]], ["Midterm"])
        self.assertEqual(to_do(self.teacher)["awaiting"], [])  # teachers don't publish

        leave = request_leave(
            self.parent,
            LeaveRequest(
                student=self.e1.student,
                starts_on=self.today,
                ends_on=self.today,
                reason="Fever",
            ),
        )
        self.assertEqual(to_do(self.teacher)["leave"], [leave])  # Alice's class teacher
        self.assertEqual(to_do(self.admin)["leave"], [leave])
        self.assertEqual(to_do(self.other_teacher)["leave"], [])
        self.assertEqual(to_do(self.principal)["leave"], [])

    def test_trend_and_low_attendance(self):
        for days_ago, alice in ((2, "A"), (1, "A"), (0, "P")):
            save_register(
                self.teacher,
                self.c,
                self.today - timedelta(days=days_ago),
                {self.e1.pk: alice, self.e2.pk: "P"},
                0,
            )
        rates = [point["rate"] for point in attendance_trend(self.admin)]
        self.assertEqual(rates, [50.0, 50.0, 100.0])
        flagged = low_attendance(self.admin)
        self.assertEqual([(r["name"], r["rate"]) for r in flagged], [("alice", 33.3)])
        self.assertEqual(low_attendance(self.foreign_teacher), [])

    def test_the_cache_is_reused_and_refreshed_when_a_register_changes(self):
        save_register(self.teacher, self.c, self.today, {self.e1.pk: "P", self.e2.pk: "A"}, 0)
        self.assertEqual(attendance_trend(self.admin)[-1]["rate"], 50.0)
        with CaptureQueriesContext(connection) as cached_call:
            attendance_trend(self.admin)
        # Only the cheap register fingerprint is read ("attendance_attendancesession"), not the
        # attendance rows table ("attendance_attendance").
        sql = " ".join(query["sql"] for query in cached_call.captured_queries)
        self.assertIn('"attendance_attendancesession"', sql)
        self.assertNotIn('"attendance_attendance"', sql)

        session = save_register(
            self.teacher, self.c, self.today, {self.e1.pk: "P", self.e2.pk: "P"}, 1, "Bob was late"
        )
        self.assertEqual(session.version, 2)
        self.assertEqual(attendance_trend(self.admin)[-1]["rate"], 100.0)  # not the cached 50

    def test_dashboard_page(self):
        save_register(self.teacher, self.c, self.today, {self.e1.pk: "P", self.e2.pk: "A"}, 0)
        self.client.force_login(self.root)
        page = self.client.get(reverse("dashboard"))
        self.assertContains(page, 'id="attendance-trend"')
        self.assertContains(page, 'id="dashboard-charts" type="application/json"')
        self.assertContains(page, "/static/vendor/chartjs/chart.umd.js")
        self.assertEqual([row["branch"] for row in page.context["charts"]["branches"]], ["North"])
        self.client.force_login(self.admin)
        page = self.client.get(reverse("dashboard"))
        self.assertEqual(page.context["charts"]["branches"], [])  # super admins only
        self.assertNotContains(page, 'id="branch-comparison"')


class FamilyDashboardTests(SchoolTestCase):
    def test_student_sees_their_own_dashboard(self):
        self.publish()
        self.client.force_login(self.e1.student.user)
        page = self.client.get(reverse("dashboard"))
        self.assertTemplateUsed(page, "reports/family_dashboard.html")
        self.assertEqual([m.exam.title for m in page.context["latest_results"]], ["Midterm"])
        self.assertNotContains(page, "Apply for leave")  # parents apply, not students

    def test_parent_switches_between_children(self):
        link_guardian(self.admin, self.e2.student, self.parent, "mother")
        self.client.force_login(self.parent)
        page = self.client.get(reverse("dashboard"))
        self.assertContains(page, 'aria-label="Choose a child"')
        self.assertEqual(page.context["student"], self.e1.student)  # first by name: alice
        bob = self.client.get(reverse("dashboard") + f"?child={self.e2.student.pk}")
        self.assertEqual(bob.context["student"], self.e2.student)
        other = self.client.get(
            reverse("dashboard") + f"?child={self.foreign_enrollment.student.pk}"
        )
        self.assertEqual(other.status_code, 404)


class RegisterVersionTests(SchoolTestCase):
    def test_every_kind_of_register_change_moves_the_fingerprint(self):
        classes = Classroom.objects.filter(pk=self.c.pk)
        seen = [register_version(classes)]
        yesterday = self.today - timedelta(days=1)
        session = save_register(
            self.teacher, self.c, yesterday, {self.e1.pk: "A", self.e2.pk: "P"}, 0
        )
        seen.append(register_version(classes))  # a new register
        save_register(
            self.teacher,
            self.c,
            yesterday,
            {self.e1.pk: "A", self.e2.pk: "A"},
            session.version,
            "Typo",
        )
        seen.append(register_version(classes))  # a correction
        leave = request_leave(
            self.parent,
            LeaveRequest(
                student=self.e1.student, starts_on=yesterday, ends_on=yesterday, reason="Ill"
            ),
        )
        decide_leave(self.teacher, leave, approve=True)
        seen.append(register_version(classes))  # an absence excused by leave
        self.assertEqual(len(set(seen)), 4, seen)
