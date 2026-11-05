from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from apps.attendance.models import Attendance, AttendanceSession
from apps.attendance.selectors import attendance_summary
from apps.attendance.services import save_register
from apps.audit.models import AuditEvent
from apps.core.exceptions import Conflict
from apps.core.testing import SchoolTestCase


class RegisterTests(SchoolTestCase):
    """Daily registers: permissions, completeness, corrections and stale writes."""

    def test_teacher_cannot_record_daily_attendance_without_homeroom(self):
        with self.assertRaises(PermissionDenied):
            save_register(
                self.other_teacher, self.c, self.today, {self.e1.pk: "P", self.e2.pk: "A"}, 0
            )

    def test_attendance_complete_roster_required(self):
        with self.assertRaises(ValidationError):
            save_register(self.teacher, self.c, self.today, {self.e1.pk: "P"}, 0)
        self.assertEqual(AttendanceSession.objects.count(), 0)

    def test_attendance_rejects_foreign_enrollment(self):
        with self.assertRaises(ValidationError):
            save_register(
                self.teacher,
                self.c,
                self.today,
                {self.e1.pk: "P", self.e2.pk: "P", self.foreign_enrollment.pk: "P"},
                0,
            )

    def test_attendance_rejects_future_date(self):
        with self.assertRaises(ValidationError):
            save_register(
                self.teacher,
                self.c,
                self.today + timedelta(days=1),
                {self.e1.pk: "P", self.e2.pk: "P"},
                0,
            )

    def test_attendance_correction_audit_and_single_register(self):
        session = save_register(
            self.teacher, self.c, self.today, {self.e1.pk: "P", self.e2.pk: "A"}, 0
        )
        with self.assertRaises(ValidationError):
            save_register(
                self.teacher,
                self.c,
                self.today,
                {self.e1.pk: "P", self.e2.pk: "P"},
                session.version,
            )
        save_register(
            self.teacher,
            self.c,
            self.today,
            {self.e1.pk: "P", self.e2.pk: "P"},
            session.version,
            "Late arrival confirmed",
        )
        self.assertEqual(AttendanceSession.objects.count(), 1)
        self.assertEqual(Attendance.objects.count(), 2)
        self.assertEqual(AuditEvent.objects.filter(action="attendance.saved").count(), 2)

    def test_stale_attendance_write_is_rejected(self):
        save_register(self.teacher, self.c, self.today, {self.e1.pk: "P", self.e2.pk: "A"}, 0)
        with self.assertRaises(Conflict):
            save_register(
                self.teacher, self.c, self.today, {self.e1.pk: "A", self.e2.pk: "A"}, 0, "retry"
            )

    def test_excused_excluded_late_included(self):
        save_register(self.teacher, self.c, self.today, {self.e1.pk: "L", self.e2.pk: "E"}, 0)
        summary = attendance_summary(Attendance.objects.all())
        self.assertEqual(summary["rate"], 100)
        self.assertEqual(summary["total"], 2)

    def test_attendance_http_post_records_all_students(self):
        self.sign_in(self.teacher)
        response = self.client.post(
            reverse("attendance") + f"?classroom={self.c.pk}&date={self.today.isoformat()}",
            {"version": 0, f"status_{self.e1.pk}": "P", f"status_{self.e2.pk}": "A"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Attendance.objects.count(), 2)
