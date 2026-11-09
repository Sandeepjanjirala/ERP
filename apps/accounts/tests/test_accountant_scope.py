"""Accountants work with fees: they see who the students are, never their marks or attendance."""

from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.policies import can_manage_account
from apps.attendance.selectors import attendance_rows, leave_requests
from apps.attendance.services import save_register
from apps.communication.models import Announcement
from apps.communication.selectors import announcements
from apps.core.testing import SchoolTestCase
from apps.exams.selectors import exams
from apps.students.selectors import students


class AccountantSelectorTests(SchoolTestCase):
    def test_students_yes_marks_attendance_and_leave_no(self):
        self.publish()
        save_register(self.teacher, self.c, self.today, {self.e1.pk: "P", self.e2.pk: "A"}, 0)
        self.assertEqual(
            {s.admission_number for s in students(self.accountant)}, {"ALICE", "BOB"}
        )  # their own branch only
        self.assertEqual(list(exams(self.accountant)), [])
        self.assertEqual(list(attendance_rows(self.accountant)), [])
        self.assertEqual(list(leave_requests(self.accountant)), [])

    def test_announcements_for_everyone_and_staff_only(self):
        made = {
            audience: Announcement.objects.create(
                branch=self.a, audience=audience, title=audience, body="x", author=self.principal
            )
            for audience in ("everyone", "staff", "parents", "students")
        }
        self.assertEqual(set(announcements(self.accountant)), {made["everyone"], made["staff"]})


class AccountantWebTests(SchoolTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.accountant)

    def test_academic_pages_are_forbidden(self):
        exam = self.publish()
        pages = [
            reverse("exams"),
            reverse("exam_detail", args=[exam.pk]),
            reverse("student_report", args=[self.e1.student.pk]),
            reverse("report_card", args=[self.e1.student.pk]),
            reverse("leave_requests"),
            reverse("students"),
            reverse("attendance"),
            reverse("reports"),
            reverse("audit"),
        ]
        for url in pages:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_overview_and_menu(self):
        page = self.client.get(reverse("dashboard"))
        self.assertTemplateUsed(page, "reports/accountant_dashboard.html")
        for hidden in ("exams", "leave_requests", "students", "attendance", "reports"):
            with self.subTest(link=hidden):
                self.assertNotContains(page, f'href="{reverse(hidden)}"')
        self.assertContains(page, f'href="{reverse("announcements")}"')


class AccountantAccountTests(SchoolTestCase):
    def test_branch_admins_create_and_manage_accountants(self):
        self.assertTrue(can_manage_account(self.admin, self.accountant))
        self.assertFalse(can_manage_account(self.principal, self.accountant))
        self.assertFalse(can_manage_account(self.accountant, self.teacher))
        self.assertFalse(self.accountant.is_school_staff)
        self.assertNotIn(User.Role.ACCOUNTANT, User.ACADEMIC)
