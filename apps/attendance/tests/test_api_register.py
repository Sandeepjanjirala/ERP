"""The attendance register over the API: same service, same locks, same rules as the web page."""

from datetime import timedelta

from apps.attendance.models import Attendance, AttendanceSession
from apps.audit.models import AuditEvent
from apps.core.testing import ApiTestCase


class RegisterApiTests(ApiTestCase):
    def url(self, classroom=None, day=None):
        url = f"/api/v1/classrooms/{(classroom or self.c).pk}/register/"
        return url + (f"?date={day.isoformat()}" if day else "")

    def body(self, version, status="P", reason=""):
        return {
            "version": version,
            "reason": reason,
            "records": [
                {"enrollment": self.e1.pk, "status": status},
                {"enrollment": self.e2.pk, "status": "A"},
            ],
        }

    def test_read_an_empty_register(self):
        self.as_user(self.teacher)
        register = self.client.get(self.url()).json()
        self.assertEqual(register["version"], 0)
        self.assertTrue(register["can_record"])
        self.assertEqual(register["date"], self.today.isoformat())
        self.assertEqual(
            [(s["admission_number"], s["status"]) for s in register["students"]],
            [("ALICE", None), ("BOB", None)],
        )

    def test_save_then_correct_with_a_reason(self):
        self.as_user(self.teacher)
        saved = self.client.put(self.url(), self.body(0))
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertEqual(saved.json()["version"], 1)
        self.assertEqual([s["status"] for s in saved.json()["students"]], ["P", "A"])

        no_reason = self.client.put(self.url(), self.body(1, status="L"))
        self.assertEqual(no_reason.status_code, 400)
        self.assertIn("reason", no_reason.json()["detail"])

        corrected = self.client.put(self.url(), self.body(1, status="L", reason="Arrived late"))
        self.assertEqual(corrected.status_code, 200)
        self.assertEqual(corrected.json()["version"], 2)
        self.assertEqual(AuditEvent.objects.filter(action="attendance.saved").count(), 2)

    def test_a_stale_version_is_a_409_conflict(self):
        self.as_user(self.teacher)
        self.client.put(self.url(), self.body(0))
        stale = self.client.put(self.url(), self.body(0, status="L", reason="Second tab"))
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["code"], "conflict")
        self.assertEqual(AttendanceSession.objects.get().version, 1)

    def test_who_may_record(self):
        cases = [
            (self.root, 200),
            (self.admin, 200),
            (self.teacher, 200),  # homeroom teacher
            (self.other_teacher, 403),  # teaches the class, but isn't its homeroom teacher
            (self.principal, 403),  # reads registers, doesn't record them
            (self.foreign_teacher, 404),  # can't see the class at all
            (self.e1.student.user, 403),
        ]
        for user, status in cases:
            with self.subTest(user=user.username):
                Attendance.objects.all().delete()  # start each case with no register
                AttendanceSession.objects.all().delete()
                self.as_user(user)
                response = self.client.put(self.url(), self.body(0))
                self.assertEqual(response.status_code, status, response.content)

    def test_read_only_staff_see_can_record_false(self):
        self.as_user(self.principal)
        self.assertFalse(self.client.get(self.url()).json()["can_record"])

    def test_dates_outside_the_rules_are_rejected(self):
        self.as_user(self.teacher)
        for day in (self.today + timedelta(days=1), self.year.starts_on - timedelta(days=1)):
            with self.subTest(day=day):
                response = self.client.get(self.url(day=day))
                self.assertEqual(response.status_code, 400)
                self.assertIn("date", response.json()["fields"])

    def test_the_whole_class_must_be_marked_once_with_valid_statuses(self):
        self.as_user(self.teacher)
        partial = {"version": 0, "records": [{"enrollment": self.e1.pk, "status": "P"}]}
        self.assertEqual(self.client.put(self.url(), partial).status_code, 400)

        twice = self.body(0)
        twice["records"][1]["enrollment"] = self.e1.pk
        response = self.client.put(self.url(), twice)
        self.assertEqual(response.status_code, 400)
        self.assertIn("records", response.json()["fields"])

        invalid = self.body(0, status="X")
        self.assertIn("records", self.client.put(self.url(), invalid).json()["fields"])
        self.assertFalse(AttendanceSession.objects.exists())
