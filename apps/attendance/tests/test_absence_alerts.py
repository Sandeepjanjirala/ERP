"""Families hear about today's absences once, after the register is really saved."""

from datetime import timedelta

from django.core import mail
from django.core.exceptions import ValidationError

from apps.attendance.models import AttendanceSession
from apps.attendance.services import save_register
from apps.attendance.tasks import alert_absent_families, correct_absence_alerts
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


class AbsenceCorrectionTests(SchoolTestCase):
    """An absence corrected the same day: those who were alerted are told it was a mistake."""

    def save(self, statuses, version=0, reason="", day=None):
        with self.captureOnCommitCallbacks(execute=True):
            return save_register(self.teacher, self.c, day or self.today, statuses, version, reason)

    def corrected(self):
        return sorted(
            Notification.objects.filter(key__startswith="absence-corrected:").values_list(
                "recipient__username", flat=True
            )
        )

    def test_the_alerted_family_hears_the_correction(self):
        session = self.save({self.e1.pk: "A", self.e2.pk: "P"})
        mail.outbox.clear()
        self.save({self.e1.pk: "L", self.e2.pk: "P"}, session.version, "Alice was late, not absent")
        self.assertEqual(self.corrected(), ["alice", "parent"])
        note = Notification.objects.get(recipient=self.parent, key__startswith="absence-corrected:")
        self.assertEqual(note.title, "Correction: alice is not absent today")
        self.assertIn("late", note.body)
        self.assertEqual(
            sorted(m.to[0] for m in mail.outbox), ["alice@example.com", "parent@example.com"]
        )

    def test_only_those_who_were_alerted(self):
        # Bob's family was never alerted (his first status was present), so nobody is corrected.
        session = self.save({self.e1.pk: "P", self.e2.pk: "P"})
        self.save({self.e1.pk: "P", self.e2.pk: "E"}, session.version, "Leave approved")
        self.assertEqual(self.corrected(), [])

    def test_once_and_only_for_today(self):
        session = self.save({self.e1.pk: "A", self.e2.pk: "P"})
        self.save({self.e1.pk: "P", self.e2.pk: "P"}, session.version, "Mistake")
        self.assertEqual(correct_absence_alerts(session.pk, [self.e1.pk]), 0)  # a retried job
        old_day = self.today - timedelta(days=2)
        old = self.save({self.e1.pk: "A", self.e2.pk: "P"}, day=old_day)
        self.save({self.e1.pk: "P", self.e2.pk: "P"}, old.version, "Old fix", day=old_day)
        self.assertEqual(len(self.corrected()), 2)  # the old register sent nothing more
