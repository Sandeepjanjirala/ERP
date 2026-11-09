"""Fee figures on the dashboards, and the collection report with its CSV export."""

import csv
import io
from datetime import timedelta

from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.fees.models import Invoice, Payment
from apps.fees.services import record_counter_payment
from apps.fees.tests.base import TOTAL, TUITION, FeesTestCase


class DashboardTests(FeesTestCase):
    def test_accountant_dashboard(self):
        issued = self.issue(due_in=0)
        record_counter_payment(self.accountant, issued[self.e1.student_id], TUITION, "cash")
        bob = issued[self.e2.student_id]
        Invoice.objects.filter(pk=bob.pk).update(
            issued_on=self.today - timedelta(days=5), due_on=self.today - timedelta(days=1)
        )
        self.client.force_login(self.accountant)
        page = self.client.get(reverse("dashboard"))
        self.assertEqual(page.context["fees"]["collected_today"], TUITION)
        self.assertEqual(page.context["fees"]["overdue"], 1)
        self.assertEqual(list(page.context["overdue_invoices"]), [bob])
        self.assertContains(page, "₹10,000.00")

    def test_fee_figures_only_for_finance_roles(self):
        self.issue()
        self.client.force_login(self.admin)
        fees = self.client.get(reverse("dashboard")).context["fees"]
        self.assertEqual((fees["billed"], fees["outstanding"]), (2 * TOTAL, 2 * TOTAL))
        self.client.force_login(self.principal)
        self.assertIsNone(self.client.get(reverse("dashboard")).context["fees"])

    def test_parents_see_fees_due_with_pay_now(self):
        alice = self.alices()
        self.client.force_login(self.parent)
        page = self.client.get(reverse("dashboard"))
        self.assertEqual(list(page.context["fees_due"]), [alice])
        self.assertContains(page, reverse("pay_online", args=[alice.pk]))
        self.client.force_login(self.e1.student.user)
        page = self.client.get(reverse("dashboard"))
        self.assertEqual(list(page.context["fees_due"]), [])  # students don't handle fees
        self.assertNotContains(page, "Pay now")


class CollectionReportTests(FeesTestCase):
    def setUp(self):
        issued = self.issue()
        self.alice, self.bob = issued[self.e1.student_id], issued[self.e2.student_id]
        record_counter_payment(self.accountant, self.alice, TUITION, "cash")
        record_counter_payment(self.accountant, self.bob, TOTAL, "upi", "=HYPERLINK(1)")

    def test_totals_by_method_and_dates(self):
        self.client.force_login(self.accountant)
        summary = self.client.get(reverse("collections")).context["summary"]
        self.assertEqual(
            (summary["received"], summary["count"], summary["excess"]), (TUITION + TOTAL, 2, 0)
        )
        methods = dict(summary["by_method"])
        self.assertEqual((methods["Cash"], methods["UPI at the counter"]), (TUITION, TOTAL))
        tomorrow = (self.today + timedelta(days=1)).isoformat()
        later = self.client.get(reverse("collections"), {"start": tomorrow, "end": tomorrow})
        self.assertEqual(later.context["summary"]["count"], 0)
        wrong = self.client.get(
            reverse("collections"), {"start": tomorrow, "end": self.today.isoformat()}
        )
        self.assertContains(wrong, "The start date must be on or before the end date.")

    def test_csv_export_is_safe_and_audited(self):
        self.client.force_login(self.accountant)
        response = self.client.get(reverse("collections"), {"format": "csv"})
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1][8:], ["10000.00", "10000.00", "0.00"])
        self.assertEqual(rows[2][7], "'=HYPERLINK(1)")  # never run as a spreadsheet formula
        event = AuditEvent.objects.get(action="fees.collections.exported")
        self.assertEqual(event.details["rows"], 2)

    def test_only_finance_staff_and_only_their_branch(self):
        for user in (self.teacher, self.principal, self.parent):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.assertEqual(self.client.get(reverse("collections")).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.get(reverse("collections"), {"branch": self.b.pk}).status_code, 404
        )
        self.assertEqual(Payment.objects.count(), 2)
