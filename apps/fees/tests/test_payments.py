"""Counter payments and receipts: never more than owed, numbers gapless, everything audited."""

from unittest import mock

from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.core.testing import pdf_text
from apps.fees.models import FeeHead, FeePlan, Receipt, ReceiptCounter
from apps.fees.pdf import balance_after, receipt_rows
from apps.fees.services import (
    cancel_invoice,
    issue_invoices,
    receipt_number,
    record_counter_payment,
    save_fee_plan,
)
from apps.fees.tasks import send_receipt
from apps.fees.tests.base import TOTAL, FeesTestCase


class CounterPaymentTests(FeesTestCase):
    def number(self, sequence, branch=None):
        return receipt_number(branch or self.a, self.year, sequence)

    def test_part_then_full_payment(self):
        invoice = self.alices()
        first = record_counter_payment(self.accountant, invoice, 500000, "cash")
        invoice.refresh_from_db()
        self.assertEqual((invoice.status, invoice.balance_paise), ("partly_paid", TOTAL - 500000))
        second = record_counter_payment(
            self.accountant, invoice, TOTAL - 500000, "upi", "UPI-REF-1234"
        )
        invoice.refresh_from_db()
        self.assertEqual((invoice.status, invoice.balance_paise), ("paid", 0))
        self.assertEqual(
            [first.receipt.number, second.receipt.number], [self.number(1), self.number(2)]
        )
        self.assertTrue(first.receipt.number.startswith(f"NORTH/{self.year.starts_on.year}-"))
        event = AuditEvent.objects.filter(action="fees.payment.recorded").latest("pk")
        self.assertEqual(
            (event.details["amount_paise"], event.details["method"], event.details["reference"]),
            (TOTAL - 500000, "upi", "UPI-REF-1234"),
        )
        self.assertEqual(event.details["receipt"], self.number(2))

    def test_counter_rules(self):
        invoice = self.alices()
        cases = [
            (self.teacher, 100, "cash", "", PermissionDenied),
            (self.principal, 100, "cash", "", PermissionDenied),
            (self.parent, 100, "cash", "", PermissionDenied),
            (self.accountant, TOTAL + 1, "cash", "", ValidationError),  # more than owed
            (self.accountant, 0, "cash", "", ValidationError),
            (self.accountant, 100, "online", "", ValidationError),  # online goes via a provider
            (self.accountant, 100, "upi", " ", ValidationError),  # UPI needs its reference
        ]
        for actor, amount, method, reference, error in cases:
            with self.subTest(actor=actor.username, amount=amount, method=method):
                with self.assertRaises(error):
                    record_counter_payment(actor, invoice, amount, method, reference)
        self.assertFalse(Receipt.objects.exists())

    def test_nothing_to_pay_on_paid_or_cancelled_invoices(self):
        issued = self.issue()
        paid, cancelled = issued[self.e1.student_id], issued[self.e2.student_id]
        record_counter_payment(self.accountant, paid, TOTAL, "cash")
        cancel_invoice(self.admin, cancelled, "Left the school")
        for invoice in (paid, cancelled):
            with self.subTest(status=invoice.status), self.assertRaises(ValidationError):
                record_counter_payment(self.accountant, invoice, 100, "cash")

    def test_a_failed_payment_leaves_no_gap_in_receipt_numbers(self):
        """The number is taken inside the payment's transaction, so a failure gives it back."""
        invoice = self.alices()
        with mock.patch("apps.fees.services.audit", side_effect=RuntimeError("disk full")):
            with self.assertRaises(RuntimeError):
                record_counter_payment(self.accountant, invoice, 100, "cash")
        invoice.refresh_from_db()
        self.assertEqual((invoice.paid_paise, Receipt.objects.count()), (0, 0))
        payment = record_counter_payment(self.accountant, invoice, 100, "cash")
        self.assertEqual(payment.receipt.sequence, 1)  # not 2
        self.assertEqual(ReceiptCounter.objects.get(branch=self.a).last_number, 1)

    def test_each_branch_numbers_its_own_receipts(self):
        bus = FeeHead.objects.create(branch=self.b, name="Bus", code="bus")
        plan = save_fee_plan(
            self.root, FeePlan(branch=self.b, year=self.year, grade="9"), {bus: 1000}
        )
        [south] = issue_invoices(self.root, plan, "Term 1", self.today)[0]
        north = record_counter_payment(self.accountant, self.alices(), 100, "cash")
        other = record_counter_payment(self.root, south, 1000, "cash")
        self.assertEqual(north.receipt.sequence, 1)
        self.assertEqual(other.receipt.number, self.number(1, self.b))
        self.assertTrue(other.receipt.number.startswith("SOUTH/"))

    def test_receipt_shows_the_balance_after_each_payment(self):
        invoice = self.alices()
        first = record_counter_payment(self.accountant, invoice, 500000, "cash")
        second = record_counter_payment(self.accountant, invoice, 250000, "cheque", "CHQ 004512")
        self.assertEqual(balance_after(first), TOTAL - 500000)
        self.assertEqual(balance_after(second), TOTAL - 750000)
        rows = dict(receipt_rows(second))
        self.assertEqual(rows["Paid by"], "Cheque (CHQ 004512)")
        self.assertEqual(rows["Amount received"], "₹2,500.00")
        self.assertNotIn("Held for refund", rows)


class ReceiptEmailTests(FeesTestCase):
    def test_the_guardian_gets_the_receipt_pdf_once(self):
        invoice = self.alices()
        with self.captureOnCommitCallbacks(execute=True):
            payment = record_counter_payment(self.accountant, invoice, TOTAL, "cash")
        [email] = mail.outbox
        self.assertEqual(email.to, ["parent@example.com"])  # Alice's mother
        self.assertIn(payment.receipt.number, email.body)
        [(filename, content, mimetype)] = email.attachments
        self.assertEqual(mimetype, "application/pdf")
        self.assertTrue(filename.startswith("receipt-NORTH-"))
        text = pdf_text(content)
        self.assertIn(payment.receipt.number, text)
        self.assertIn("Test Organisation", text)
        self.assertIn("Generated by EduNexa", text)
        self.assertEqual(send_receipt(payment.pk), 0)  # a retried job sends nothing more
        self.assertEqual(len(mail.outbox), 1)

    def test_no_guardian_no_email(self):
        bob = self.issue()[self.e2.student_id]
        with self.captureOnCommitCallbacks(execute=True):
            record_counter_payment(self.accountant, bob, 100, "cash")
        self.assertEqual(mail.outbox, [])


class InvoiceListPageTests(FeesTestCase):
    def test_finance_staff_and_parents(self):
        self.issue()
        self.client.force_login(self.accountant)
        page = self.client.get(reverse("fees"))
        self.assertEqual(len(page.context["page_obj"]), 2)
        self.assertContains(page, "₹25,000.00")  # billed: two invoices of ₹12,500
        self.client.force_login(self.parent)
        page = self.client.get(reverse("fees"))
        self.assertEqual([i.student for i in page.context["page_obj"]], [self.e1.student])
        self.assertNotContains(page, "Outstanding")  # no school-wide totals for parents
        for user in (self.teacher, self.principal, self.e1.student.user):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.assertEqual(self.client.get(reverse("fees")).status_code, 403)

    def test_filters_and_search(self):
        issued = self.issue(due_in=0)
        record_counter_payment(self.accountant, issued[self.e1.student_id], TOTAL, "cash")
        self.client.force_login(self.accountant)
        rows = lambda query: list(self.client.get(reverse("fees") + query).context["page_obj"])  # noqa: E731
        self.assertEqual([i.student_id for i in rows("?show=paid")], [self.e1.student_id])
        self.assertEqual([i.student_id for i in rows("?show=open")], [self.e2.student_id])
        self.assertEqual(rows("?show=overdue"), [])  # due today
        self.assertEqual([i.student_id for i in rows("?show=all&q=bob")], [self.e2.student_id])
        bob = issued[self.e2.student_id]
        self.assertEqual(rows(f"?show=all&q=%23{bob.pk}"), [bob])
