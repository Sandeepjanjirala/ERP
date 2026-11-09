"""The rules the fee tables enforce themselves, whatever code writes to them."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase
from django.utils import timezone

from apps.core.testing import SchoolTestCase
from apps.fees.models import FeeHead, FeePlan, FeePlanItem, Invoice, Payment, rupees


class RupeesTests(SimpleTestCase):
    def test_indian_digit_grouping(self):
        cases = {
            0: "₹0.00",
            5: "₹0.05",
            1250000: "₹12,500.00",
            12500050: "₹1,25,000.50",
            100000000: "₹10,00,000.00",
            -2500: "-₹25.00",
        }
        for paise, text in cases.items():
            with self.subTest(paise=paise):
                self.assertEqual(rupees(paise), text)


class FeeModelTests(SchoolTestCase):
    def invoice(self, **fields):
        values = {
            "branch": self.a,
            "year": self.year,
            "student": self.e1.student,
            "title": "Term 1",
            "issued_on": self.today,
            "due_on": self.today + timedelta(days=14),
            "total_paise": 1000000,
            "issued_by": self.admin,
        }
        return Invoice(**{**values, **fields})

    def test_plan_rules(self):
        tuition = FeeHead.objects.create(branch=self.a, name="Tuition", code="tuition")
        plan = FeePlan.objects.create(branch=self.a, year=self.year, grade="9")
        with self.assertRaises(ValidationError):
            FeePlan.objects.create(branch=self.a, year=self.year, grade="9")  # one per grade
        with self.assertRaisesMessage(ValidationError, "No classroom"):
            FeePlan.objects.create(branch=self.a, year=self.year, grade="Class 42")
        south = FeeHead.objects.create(branch=self.b, name="Bus", code="bus")
        with self.assertRaisesMessage(ValidationError, "plan's branch"):
            FeePlanItem.objects.create(plan=plan, head=south, amount_paise=100)
        with self.assertRaises(ValidationError):
            FeePlanItem.objects.create(plan=plan, head=tuition, amount_paise=0)

    def test_invoice_rules(self):
        cases = [
            ({"paid_paise": 1000001}, "paid more than the total"),
            ({"due_on": self.today - timedelta(days=1)}, "due before it was issued"),
            ({"status": "cancelled", "paid_paise": 100}, "cancelled after a payment"),
            ({"student": self.foreign_enrollment.student}, "a student of another branch"),
        ]
        for fields, why in cases:
            with self.subTest(why=why), self.assertRaises(ValidationError):
                self.invoice(**fields).save()

    def test_paid_never_exceeds_total_even_without_validation(self):
        """The database itself refuses it, not just Django's checks."""
        invoice = self.invoice()
        invoice.save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Invoice.objects.filter(pk=invoice.pk).update(paid_paise=1000001)

    def test_balance_and_overdue_are_computed(self):
        invoice = self.invoice(paid_paise=400000, due_on=self.today)
        self.assertEqual(invoice.balance_paise, 600000)
        self.assertFalse(invoice.is_overdue())
        self.assertTrue(invoice.is_overdue(self.today + timedelta(days=1)))
        invoice.status, invoice.paid_paise = Invoice.Status.CANCELLED, 0
        self.assertEqual(invoice.balance_paise, 0)
        self.assertFalse(invoice.is_overdue(self.today + timedelta(days=30)))

    def test_a_provider_payment_is_recorded_once(self):
        invoice = self.invoice()
        invoice.save()
        fields = {
            "invoice": invoice,
            "method": "online",
            "amount_paise": 100,
            "applied_paise": 100,
            "gateway": "sandbox",
            "gateway_payment_id": "pay_123",
            "paid_at": timezone.now(),
        }
        Payment.objects.create(**fields)
        with self.assertRaises(ValidationError):
            Payment.objects.create(**fields)
        Payment.objects.create(**{**fields, "gateway_payment_id": ""})  # counter payments
        Payment.objects.create(**{**fields, "gateway_payment_id": ""})
        with self.assertRaises(ValidationError):
            Payment.objects.create(**{**fields, "gateway_payment_id": "", "applied_paise": 101})

    def test_receipt_prefix(self):
        self.assertEqual(self.a.receipt_code, "NORTH")
        self.a.receipt_prefix = "NTH"
        self.assertEqual(self.a.receipt_code, "NTH")
        self.a.receipt_prefix = "nth"
        with self.assertRaises(ValidationError):
            self.a.full_clean()
