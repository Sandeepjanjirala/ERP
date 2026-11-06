from datetime import timedelta

from django.core import mail

from apps.communication.models import Notification
from apps.fees.services import cancel_invoice, record_counter_payment
from apps.fees.tasks import remind_overdue_invoices
from apps.fees.tests.base import TOTAL, FeesTestCase


class OverdueReminderTests(FeesTestCase):
    def reminders(self):
        return Notification.objects.filter(key__startswith="reminder:")

    def test_overdue_families_are_reminded_once_a_week(self):
        alice = self.alices(due_in=1)
        tomorrow = self.today + timedelta(days=1)
        self.assertEqual(remind_overdue_invoices(tomorrow.isoformat()), 0)  # due, not overdue

        late = self.today + timedelta(days=2)
        mail.outbox.clear()
        sent = remind_overdue_invoices(late.isoformat())
        reminder = self.reminders().get(recipient=self.parent)
        self.assertGreaterEqual(sent, 1)
        self.assertIn("₹12,500.00 is still owed for alice", reminder.body)
        self.assertEqual(reminder.url, f"/fees/invoices/{alice.pk}/")
        self.assertIn("Fee overdue: Term 1", [m.subject for m in mail.outbox])

        # The job runs daily: every remaining day of that week sends nothing more...
        sunday = late + timedelta(days=7 - late.isoweekday())
        day = late
        while day <= sunday:
            remind_overdue_invoices(day.isoformat())
            day += timedelta(days=1)
        self.assertEqual(self.reminders().filter(recipient=self.parent).count(), 1)
        # ...and the next Monday starts a new week: one more reminder.
        remind_overdue_invoices((sunday + timedelta(days=1)).isoformat())
        self.assertEqual(self.reminders().filter(recipient=self.parent).count(), 2)

    def test_paid_and_cancelled_invoices_are_left_alone(self):
        issued = self.issue(due_in=1)
        record_counter_payment(self.accountant, issued[self.e1.student_id], TOTAL, "cash")
        cancel_invoice(self.admin, issued[self.e2.student_id], "Left the school")
        self.assertEqual(remind_overdue_invoices((self.today + timedelta(days=5)).isoformat()), 0)
        self.assertFalse(self.reminders().exists())
