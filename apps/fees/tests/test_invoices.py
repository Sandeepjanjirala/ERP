"""Fee plans, issuing invoices, concessions and cancellations, at the service layer."""

from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError

from apps.audit.models import AuditEvent
from apps.fees.models import FeePlan, Invoice
from apps.fees.selectors import invoices, overdue, totals
from apps.fees.services import cancel_invoice, grant_concession, issue_invoices, save_fee_plan
from apps.fees.tests.base import TOTAL, TRANSPORT, TUITION, FeesTestCase


class PlanTests(FeesTestCase):
    def test_only_admins_set_up_plans(self):
        for actor in (self.accountant, self.principal, self.teacher, self.parent):
            with self.subTest(actor=actor.username), self.assertRaises(PermissionDenied):
                save_fee_plan(actor, self.plan, {self.tuition: 1})
        with self.assertRaises(PermissionDenied):  # another branch's admin can't either
            save_fee_plan(self.admin, FeePlan(branch=self.b, year=self.year, grade="9"), {})

    def test_changing_a_plan_is_audited_and_leaves_issued_invoices_alone(self):
        invoice = self.alices()
        save_fee_plan(self.admin, self.plan, {self.tuition: TUITION + 50000})
        event = AuditEvent.objects.filter(action="fees.plan.saved").latest("pk")
        self.assertEqual(event.details["before"], {"Tuition": TUITION, "Transport": TRANSPORT})
        self.assertEqual(event.details["after"], {"Tuition": TUITION + 50000})
        invoice.refresh_from_db()
        self.assertEqual(invoice.total_paise, TOTAL)  # already issued: unchanged
        with self.assertRaises(ValidationError):
            save_fee_plan(self.admin, self.plan, {self.tuition: 0})


class IssueTests(FeesTestCase):
    def test_everyone_in_the_grade_is_invoiced_once(self):
        issued = self.issue()
        self.assertEqual(set(issued), {self.e1.student_id, self.e2.student_id})  # not Charlie
        alice = issued[self.e1.student_id]
        self.assertEqual((alice.total_paise, alice.status), (TOTAL, "issued"))
        self.assertEqual(
            [(line.description, line.amount_paise) for line in alice.lines.all()],
            [("Transport", TRANSPORT), ("Tuition", TUITION)],  # the plan's order: by name
        )
        again, skipped = issue_invoices(self.accountant, self.plan, "Term 1", alice.due_on)
        self.assertEqual((again, skipped), ([], 2))
        self.assertEqual(len(self.issue(title="Term 2")), 2)

    def test_who_may_issue(self):
        self.issue(actor=self.admin)
        for actor in (self.principal, self.teacher, self.parent):
            with self.subTest(actor=actor.username), self.assertRaises(PermissionDenied):
                self.issue(actor=actor, title="Term 3")


class ConcessionTests(FeesTestCase):
    def test_concession_reduces_the_total_and_is_audited(self):
        invoice = grant_concession(self.admin, self.alices(), 250000, "Sibling discount")
        self.assertEqual(
            (invoice.total_paise, invoice.balance_paise), (TOTAL - 250000, TOTAL - 250000)
        )
        event = AuditEvent.objects.get(action="fees.concession.granted")
        self.assertEqual(event.details["reason"], "Sibling discount")
        self.assertEqual(
            (event.details["total_before"], event.details["total_after"]), (TOTAL, TOTAL - 250000)
        )

    def test_a_full_concession_settles_the_invoice(self):
        invoice = grant_concession(self.admin, self.alices(), TOTAL, "Scholarship")
        self.assertEqual((invoice.status, invoice.balance_paise), ("paid", 0))

    def test_concession_rules(self):
        invoice = self.alices()
        cases = [
            (self.accountant, 100, "Discount", PermissionDenied),  # admins only
            (self.admin, TOTAL + 1, "Too much", ValidationError),
            (self.admin, 0, "Nothing", ValidationError),
            (self.admin, 100, "  ", ValidationError),  # a reason is required
        ]
        for actor, amount, reason, error in cases:
            with self.subTest(amount=amount, reason=reason), self.assertRaises(error):
                grant_concession(actor, invoice, amount, reason)


class CancelTests(FeesTestCase):
    def test_cancel_an_unpaid_invoice(self):
        invoice = cancel_invoice(self.admin, self.alices(), "Issued twice by mistake")
        self.assertEqual((invoice.status, invoice.balance_paise), ("cancelled", 0))
        self.assertTrue(AuditEvent.objects.filter(action="fees.invoice.cancelled").exists())
        with self.assertRaises(ValidationError):  # once only
            cancel_invoice(self.admin, invoice, "Again")

    def test_cancel_rules(self):
        invoice = self.alices()
        with self.assertRaises(PermissionDenied):
            cancel_invoice(self.accountant, invoice, "No")
        with self.assertRaises(ValidationError):
            cancel_invoice(self.admin, invoice, "")


class InvoiceScopeTests(FeesTestCase):
    def test_who_sees_which_invoices(self):
        issued = self.issue()
        alice, bob = issued[self.e1.student_id], issued[self.e2.student_id]
        cases = [
            (self.root, {alice, bob}),
            (self.admin, {alice, bob}),
            (self.accountant, {alice, bob}),
            (self.parent, {alice}),  # Alice's mother
            (self.principal, set()),
            (self.teacher, set()),
            (self.e1.student.user, set()),
            (self.foreign_teacher, set()),
        ]
        for user, expected in cases:
            with self.subTest(user=user.username):
                self.assertEqual(set(invoices(user)), expected)

    def test_overdue_and_totals(self):
        self.issue(due_in=0)  # due today: not overdue yet
        tomorrow = self.today + timedelta(days=1)
        self.assertEqual(overdue(Invoice.objects.all()).count(), 0)
        self.assertEqual(overdue(Invoice.objects.all(), tomorrow).count(), 2)
        self.assertEqual(
            totals(Invoice.objects.all()),
            {"billed": 2 * TOTAL, "collected": 0, "outstanding": 2 * TOTAL},
        )
