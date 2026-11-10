from datetime import timedelta

from apps.core.testing import SchoolTestCase
from apps.fees.models import FeeHead, FeePlan
from apps.fees.services import issue_invoices, save_fee_plan

TUITION, TRANSPORT = 1000000, 250000  # ₹10,000 and ₹2,500, in paise
TOTAL = TUITION + TRANSPORT


class FeesTestCase(SchoolTestCase):
    """A grade 9 plan in North: Alice and Bob are invoiced; Charlie (South) is not."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.tuition = FeeHead.objects.create(branch=cls.a, name="Tuition", code="tuition")
        cls.transport = FeeHead.objects.create(branch=cls.a, name="Transport", code="transport")
        cls.plan = save_fee_plan(
            cls.admin,
            FeePlan(branch=cls.a, year=cls.year, grade=cls.grade9),
            {cls.tuition: TUITION, cls.transport: TRANSPORT},
        )

    def issue(self, title="Term 1", due_in=14, actor=None):
        created, _ = issue_invoices(
            actor or self.accountant, self.plan, title, self.today + timedelta(days=due_in)
        )
        return {invoice.student_id: invoice for invoice in created}

    def alices(self, **kwargs):
        return self.issue(**kwargs)[self.e1.student_id]
