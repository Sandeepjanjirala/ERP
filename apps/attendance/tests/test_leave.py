"""Leave requests: parent asks, the class teacher decides, approved days become Excused."""

from datetime import timedelta

from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from apps.attendance.models import Attendance, AttendanceSession, LeaveRequest
from apps.attendance.selectors import daily_register, leave_requests
from apps.attendance.services import decide_leave, request_leave, save_register
from apps.audit.models import AuditEvent
from apps.communication.models import Notification
from apps.core.testing import ApiTestCase, SchoolTestCase


class LeaveTestCase(SchoolTestCase):
    def ask(self, student=None, starts=0, ends=1, parent=None):
        """A request for Alice (by default) from `starts` to `ends` days from today."""
        leave = LeaveRequest(
            student=student or self.e1.student,
            starts_on=self.today + timedelta(days=starts),
            ends_on=self.today + timedelta(days=ends),
            reason="Family wedding",
        )
        with self.captureOnCommitCallbacks(execute=True):
            return request_leave(parent or self.parent, leave)

    def decide(self, leave, approve=True, note="", actor=None):
        with self.captureOnCommitCallbacks(execute=True):
            return decide_leave(actor or self.teacher, leave, approve, note)


class RequestTests(LeaveTestCase):
    def test_a_parent_asks_and_the_class_teacher_is_told(self):
        leave = self.ask()
        self.assertEqual((leave.status, leave.requested_by), ("pending", self.parent))
        notice = Notification.objects.get(kind="leave")
        self.assertEqual(notice.recipient, self.teacher)  # Alice's class teacher
        self.assertEqual(mail.outbox[0].to, ["teacher@example.com"])
        self.assertTrue(AuditEvent.objects.filter(action="leave.requested").exists())

    def test_request_rules(self):
        self.ask()  # today and tomorrow
        cases = [
            # Bob is not this parent's child.
            (lambda: self.ask(student=self.e2.student), PermissionDenied),
            # Teachers don't ask for leave on a student's behalf.
            (lambda: self.ask(parent=self.teacher, starts=5, ends=5), PermissionDenied),
            # Overlaps the request above.
            (lambda: self.ask(starts=1, ends=3), ValidationError),
            # Backwards dates.
            (lambda: self.ask(starts=10, ends=8), ValidationError),
            # Longer than a month.
            (lambda: self.ask(starts=10, ends=50), ValidationError),
            # Before Alice joined (outside the year).
            (lambda: self.ask(starts=-200, ends=-199), ValidationError),
        ]
        for number, (attempt, error) in enumerate(cases):
            with self.subTest(case=number), self.assertRaises(error):
                attempt()
        self.assertEqual(LeaveRequest.objects.count(), 1)


class DecisionTests(LeaveTestCase):
    def test_approval_turns_recorded_absences_into_excused(self):
        yesterday = self.today - timedelta(days=1)
        session = save_register(
            self.teacher, self.c, yesterday, {self.e1.pk: "A", self.e2.pk: "A"}, 0
        )
        leave = self.ask(starts=-1, ends=0)
        leave = self.decide(leave)
        self.assertEqual(leave.status, "approved")
        records = dict(session.records.values_list("enrollment_id", "status"))
        self.assertEqual(records, {self.e1.pk: "E", self.e2.pk: "A"})  # only Alice's
        session.refresh_from_db()
        self.assertEqual(session.version, 2)  # an open register tab must reload
        event = AuditEvent.objects.get(action="leave.approved")
        self.assertEqual(event.details["excused_days"], [yesterday.isoformat()])
        told = set(
            Notification.objects.filter(key=f"leave-decided:{leave.pk}").values_list(
                "recipient__username", flat=True
            )
        )
        self.assertEqual(told, {"parent", "alice"})

    def test_present_days_stay_present(self):
        yesterday = self.today - timedelta(days=1)
        session = save_register(
            self.teacher, self.c, yesterday, {self.e1.pk: "P", self.e2.pk: "A"}, 0
        )
        self.decide(self.ask(starts=-1, ends=0))
        self.assertEqual(session.records.get(enrollment=self.e1).status, "P")
        session.refresh_from_db()
        self.assertEqual(session.version, 1)

    def test_decision_rules(self):
        leave = self.ask()
        cases = [
            (self.other_teacher, True, "", PermissionDenied),  # teaches, but not the class teacher
            (self.principal, True, "", PermissionDenied),
            (self.parent, True, "", PermissionDenied),
            (self.teacher, False, "  ", ValidationError),  # a refusal needs a reason
        ]
        for actor, approve, note, error in cases:
            with self.subTest(actor=actor.username, approve=approve):
                with self.assertRaises(error):
                    self.decide(leave, approve, note, actor=actor)
        refused = self.decide(leave, approve=False, note="Exams that week", actor=self.admin)
        self.assertEqual(refused.status, "rejected")
        with self.assertRaises(ValidationError):  # already decided
            self.decide(leave)

    def test_the_register_suggests_excused_for_approved_leave(self):
        tomorrow = self.today + timedelta(days=1)
        leave = self.ask(starts=1, ends=2)
        self.assertEqual(daily_register(self.c, tomorrow)["on_leave"], set())  # still pending
        self.decide(leave)
        self.assertEqual(daily_register(self.c, tomorrow)["on_leave"], {self.e1.pk})
        self.assertEqual(daily_register(self.c, self.today)["on_leave"], set())


class ScopeTests(LeaveTestCase):
    def test_who_sees_which_requests(self):
        leave = self.ask()
        for user, visible in (
            (self.parent, True),
            (self.e1.student.user, True),
            (self.e2.student.user, False),
            (self.teacher, True),
            (self.admin, True),
            (self.foreign_teacher, False),
        ):
            with self.subTest(user=user.username):
                self.assertEqual(leave in leave_requests(user), visible)


class LeaveWebTests(LeaveTestCase):
    def test_parent_applies_and_teacher_approves(self):
        self.client.force_login(self.parent)
        response = self.client.post(
            reverse("leave_create"),
            {
                "student": self.e1.student.pk,
                "starts_on": self.today.isoformat(),
                "ends_on": self.today.isoformat(),
                "reason": "Fever",
            },
        )
        self.assertRedirects(response, reverse("leave_requests"))
        leave = LeaveRequest.objects.get()

        self.client.force_login(self.teacher)
        page = self.client.get(reverse("leave_requests"))
        self.assertContains(page, reverse("leave_decide", args=[leave.pk]))
        self.client.post(reverse("leave_decide", args=[leave.pk]), {"decision": "approve"})
        leave.refresh_from_db()
        self.assertEqual(leave.status, "approved")

        register = self.client.get(
            reverse("attendance") + f"?classroom={self.c.pk}&date={self.today.isoformat()}"
        )
        self.assertContains(register, "On approved leave")
        self.assertEqual(register.context["form"][f"status_{self.e1.pk}"].initial, "E")

    def test_staff_who_cannot_decide_see_no_buttons(self):
        leave = self.ask()
        self.client.force_login(self.other_teacher)
        page = self.client.get(reverse("leave_requests"))
        self.assertContains(page, "Family wedding")  # they can see it...
        self.assertNotContains(page, reverse("leave_decide", args=[leave.pk]))  # ...not decide it
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse("leave_create")).status_code, 403)


class LeaveApiTests(ApiTestCase):
    def test_flow(self):
        self.as_user(self.parent)
        with self.captureOnCommitCallbacks(execute=True):
            created = self.client.post(
                "/api/v1/leave-requests/",
                {
                    "student": self.e1.student.pk,
                    "starts_on": self.today.isoformat(),
                    "ends_on": self.today.isoformat(),
                    "reason": "Fever",
                },
            )
        self.assertEqual(created.status_code, 201, created.content)
        leave_id = created.json()["id"]
        classmate = self.client.post(
            "/api/v1/leave-requests/",
            {
                "student": self.e2.student.pk,
                "starts_on": self.today.isoformat(),
                "ends_on": self.today.isoformat(),
                "reason": "x",
            },
        )
        self.assertIn("student", classmate.json()["fields"])
        self.assertEqual(
            self.client.post(f"/api/v1/leave-requests/{leave_id}/approve/").status_code, 403
        )

        self.as_user(self.teacher)
        refused = self.client.post(f"/api/v1/leave-requests/{leave_id}/reject/", {})
        self.assertEqual(refused.status_code, 400)
        approved = self.client.post(f"/api/v1/leave-requests/{leave_id}/approve/")
        self.assertEqual(approved.json()["status"], "approved")
        register = self.client.get(f"/api/v1/classrooms/{self.c.pk}/register/").json()
        on_leave = {row["enrollment"]: row["on_leave"] for row in register["students"]}
        self.assertEqual(on_leave, {self.e1.pk: True, self.e2.pk: False})
        self.assertEqual(
            self.client.post("/api/v1/leave-requests/", {}).status_code, 403
        )  # teachers don't apply


class SessionLockTests(LeaveTestCase):
    def test_a_register_saved_with_the_old_version_after_an_excuse_is_refused(self):
        yesterday = self.today - timedelta(days=1)
        session = save_register(
            self.teacher, self.c, yesterday, {self.e1.pk: "A", self.e2.pk: "P"}, 0
        )
        self.decide(self.ask(starts=-1, ends=-1))
        with self.assertRaises(ValidationError):  # Conflict is a ValidationError
            save_register(
                self.teacher,
                self.c,
                yesterday,
                {self.e1.pk: "A", self.e2.pk: "P"},
                session.version,
                "Typo",
            )
        self.assertEqual(Attendance.objects.get(session=session, enrollment=self.e1).status, "E")
        self.assertEqual(AttendanceSession.objects.get(pk=session.pk).version, 2)


class LeaveWebErrorTests(LeaveTestCase):
    def test_errors_are_shown_not_raised(self):
        self.ask()  # today and tomorrow
        self.client.force_login(self.parent)
        overlap = self.client.post(
            reverse("leave_create"),
            {
                "student": self.e1.student.pk,
                "starts_on": self.today.isoformat(),
                "ends_on": self.today.isoformat(),
                "reason": "Again",
            },
        )
        self.assertContains(overlap, "overlap another request")

        leave = LeaveRequest.objects.get()
        self.client.force_login(self.teacher)
        url = reverse("leave_decide", args=[leave.pk])
        no_reason = self.client.post(url, {"decision": "reject", "note": ""}, follow=True)
        self.assertContains(no_reason, "Say why the request is not approved")
        nonsense = self.client.post(url, {"decision": "maybe"}, follow=True)
        self.assertContains(nonsense, "Choose approve or not approve")
        leave.refresh_from_db()
        self.assertEqual(leave.status, "pending")

        pending = self.client.get(reverse("leave_requests") + "?status=pending")
        self.assertEqual(list(pending.context["page_obj"]), [leave])
        approved = self.client.get(reverse("leave_requests") + "?status=approved")
        self.assertEqual(list(approved.context["page_obj"]), [])
