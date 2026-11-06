"""Families hear about today's absences once, after the register is really saved."""

from datetime import timedelta

from django.core import mail
from django.core.exceptions import ValidationError

from apps.attendance.models import AttendanceSession
from apps.attendance.services import save_register
from apps.attendance.tasks import alert_absent_families
from apps.communication.models import Notification
from apps.core.testing import SchoolTestCase


def alerted():
    return sorted(
        Notification.objects.filter(kind="absence").values_list("recipient__username", flat=True)
    )


class AbsenceAlertTests(SchoolTestCase):
    def save(self, statuses, version=0, reason="", day=None):
        with self.captureOnCommitCallbacks(execute=True):
            return save_register(self.teacher, self.c, day or self.today, statuses, version, reason)

    def test_the_absent_student_and_their_guardians_are_alerted(self):
        self.save({self.e1.pk: "A", self.e2.pk: "P"})
        self.assertEqual(alerted(), ["alice", "parent"])  # Bob was present
        self.assertEqual(
            sorted(m.to[0] for m in mail.outbox), ["alice@example.com", "parent@example.com"]
        )
        alert = Notification.objects.get(recipient=self.parent)
        self.assertEqual(alert.title, "alice was marked absent today")
        self.assertEqual(alert.url, f"/students/{self.e1.student.pk}/report/")

    def test_a_correction_alerts_only_the_newly_absent(self):
        session = self.save({self.e1.pk: "A", self.e2.pk: "P"})
        mail.outbox.clear()
        self.save({self.e1.pk: "A", self.e2.pk: "A"}, session.version, "Bob left early")
        self.assertEqual(alerted(), ["alice", "bob", "parent"])  # Alice's family once only
        self.assertEqual([m.to[0] for m in mail.outbox], ["bob@example.com"])

    def test_old_registers_send_nothing(self):
        self.save({self.e1.pk: "A", self.e2.pk: "A"}, day=self.today - timedelta(days=3))
        self.assertEqual(alerted(), [])

    def test_a_student_corrected_to_present_before_the_job_runs_is_skipped(self):
        session = self.save({self.e1.pk: "P", self.e2.pk: "P"})
        session.records.filter(enrollment=self.e1).update(status="A")
        session.records.filter(enrollment=self.e1).update(status="P")  # corrected again
        self.assertEqual(alert_absent_families(session.pk, [self.e1.pk]), 0)

    def test_running_the_job_twice_alerts_once(self):
        self.save({self.e1.pk: "A", self.e2.pk: "P"})
        session = AttendanceSession.objects.get()
        self.assertEqual(alert_absent_families(session.pk, [self.e1.pk]), 0)
        self.assertEqual(len(mail.outbox), 2)

    def test_a_rejected_save_alerts_nobody(self):
        with self.assertRaises(ValidationError):
            self.save({self.e1.pk: "A"})  # Bob is missing: the service refuses the register
        self.assertEqual(alerted(), [])
