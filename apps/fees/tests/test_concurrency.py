"""Real threads, real transactions, PostgreSQL row locks: money can't be double-counted."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest import skipUnless

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase

from apps.accounts.models import User
from apps.core.testing import SchoolTestCase
from apps.fees.models import FeeHead, FeePlan, Invoice, Receipt
from apps.fees.services import issue_invoices, record_counter_payment, save_fee_plan
from apps.fees.tests.base import TOTAL, TRANSPORT, TUITION


@skipUnless(
    connection.vendor == "postgresql",
    "Requires PostgreSQL row locks; run the provided PostgreSQL CI job or Docker test command.",
)
class FeeConcurrencyTests(TransactionTestCase):
    def setUp(self):
        SchoolTestCase.setUpTestData.__func__(type(self))
        tuition = FeeHead.objects.create(branch=self.a, name="Tuition", code="tuition")
        transport = FeeHead.objects.create(branch=self.a, name="Transport", code="transport")
        plan = save_fee_plan(
            self.admin,
            FeePlan(branch=self.a, year=self.year, grade="9"),
            {tuition: TUITION, transport: TRANSPORT},
        )
        created, _ = issue_invoices(self.accountant, plan, "Term 1", self.today + timedelta(days=7))
        self.invoices = {invoice.student_id: invoice for invoice in created}

    def together(self, operations):
        """Start every operation at the same moment, each in its own thread and transaction."""
        barrier = Barrier(len(operations))

        def run(operation):
            close_old_connections()
            try:
                actor = User.objects.get(pk=self.accountant.pk)
                barrier.wait(timeout=10)
                operation(actor)
                return "paid"
            except ValidationError:
                return "refused"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(operations)) as pool:
            return sorted(pool.map(run, operations, timeout=60))

    def test_two_cashiers_paying_the_same_balance(self):
        alice = self.invoices[self.e1.student_id]
        pay_all = lambda actor: record_counter_payment(actor, alice, TOTAL, "cash")  # noqa: E731
        self.assertEqual(self.together([pay_all, pay_all]), ["paid", "refused"])
        alice.refresh_from_db()
        self.assertEqual((alice.paid_paise, alice.status), (TOTAL, "paid"))
        self.assertEqual(Receipt.objects.count(), 1)

    def test_receipt_numbers_stay_gapless_under_concurrent_payments(self):
        alice, bob = self.invoices[self.e1.student_id], self.invoices[self.e2.student_id]

        def pay(invoice):
            return lambda actor: record_counter_payment(actor, invoice, 1000, "cash")

        outcomes = self.together([pay(alice), pay(bob)] * 4)
        self.assertEqual(outcomes, ["paid"] * 8)
        sequences = sorted(Receipt.objects.values_list("sequence", flat=True))
        self.assertEqual(sequences, list(range(1, 9)))
        paid = dict(Invoice.objects.values_list("pk", "paid_paise"))
        self.assertEqual((paid[alice.pk], paid[bob.pk]), (4000, 4000))
