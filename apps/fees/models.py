"""Fees: what a school charges (heads and plans), what each student owes (invoices), and the
money that came in (payments and receipts).

Every amount is a whole number of paise (₹1 = 100 paise), as payment providers use: no rounding,
ever. Screens and PDFs format them as rupees.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.academics.models import AcademicYear, Classroom
from apps.core.models import ValidatedModel
from apps.organization.models import Branch
from apps.students.models import Student


def rupees(paise):
    """12500050 -> "₹1,25,000.50" style text, Indian digit grouping."""
    sign = "-" if paise < 0 else ""
    whole, fraction = divmod(abs(paise), 100)
    digits = str(whole)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        digits = ",".join([head, *groups, tail]) if head else ",".join([*groups, tail])
    return f"{sign}₹{digits}.{fraction:02d}"


class FeeHead(ValidatedModel):
    """A kind of charge, such as Tuition or Transport."""

    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="fee_heads")
    name = models.CharField(max_length=60)
    code = models.SlugField(max_length=20)

    class Meta:
        ordering = ["name", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["branch", "code"], name="fee_head_code_per_branch")
        ]

    def __str__(self):
        return self.name


class FeePlan(ValidatedModel):
    """What a grade pays in a year: one plan per branch, year and grade.

    `grade` is the classroom's grade text ("Class 10") until Phase 5 adds a Grade model; that
    migration will point each plan at the Grade with the same branch and name, then drop the text.
    """

    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="fee_plans")
    year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name="fee_plans")
    grade = models.CharField(max_length=25)

    class Meta:
        ordering = ["grade", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "year", "grade"], name="one_fee_plan_per_grade"
            )
        ]

    def clean(self):
        if (
            self.branch_id
            and self.year_id
            and self.grade
            and not Classroom.objects.filter(
                branch_id=self.branch_id, year_id=self.year_id, grade=self.grade
            ).exists()
        ):
            raise ValidationError({"grade": "No classroom in this branch and year has that grade."})

    def __str__(self):
        return f"{self.grade} · {self.year}"


class FeePlanItem(ValidatedModel):
    plan = models.ForeignKey(FeePlan, on_delete=models.PROTECT, related_name="items")
    head = models.ForeignKey(FeeHead, on_delete=models.PROTECT)
    amount_paise = models.PositiveIntegerField()

    class Meta:
        ordering = ["head__name", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["plan", "head"], name="fee_head_once_per_plan"),
            models.CheckConstraint(condition=Q(amount_paise__gt=0), name="plan_item_positive"),
        ]

    def clean(self):
        if self.plan_id and self.head_id and self.plan.branch_id != self.head.branch_id:
            raise ValidationError("The fee head must belong to the plan's branch.")


class Invoice(ValidatedModel):
    """What one student owes. "Overdue" is not a status: it is computed from the due date and
    the balance, so it can never be out of date."""

    class Status(models.TextChoices):
        ISSUED = "issued", "Issued"
        PARTLY_PAID = "partly_paid", "Partly paid"
        PAID = "paid", "Paid"
        CANCELLED = "cancelled", "Cancelled"

    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="invoices")
    year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name="invoices")
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name="invoices")
    plan = models.ForeignKey(
        FeePlan, on_delete=models.PROTECT, null=True, blank=True, related_name="invoices"
    )
    title = models.CharField(max_length=80)
    issued_on = models.DateField()
    due_on = models.DateField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ISSUED)
    total_paise = models.PositiveIntegerField()
    paid_paise = models.PositiveIntegerField(default=0)
    version = models.PositiveIntegerField(default=1)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=250, blank=True)

    class Meta:
        ordering = ["-issued_on", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(paid_paise__lte=F("total_paise")), name="paid_never_exceeds_total"
            ),
            models.CheckConstraint(
                condition=Q(due_on__gte=F("issued_on")), name="due_on_or_after_issue"
            ),
            models.CheckConstraint(
                condition=~Q(status="cancelled") | Q(paid_paise=0),
                name="only_unpaid_invoices_cancelled",
            ),
            models.UniqueConstraint(
                fields=["student", "plan", "title"],
                condition=Q(plan__isnull=False),
                name="one_invoice_per_plan_and_title",
            ),
        ]

    def clean(self):
        if self.student_id and self.branch_id and self.student.user.branch_id != self.branch_id:
            raise ValidationError("The student must belong to the invoice's branch.")

    @property
    def balance_paise(self):
        return 0 if self.status == self.Status.CANCELLED else self.total_paise - self.paid_paise

    def is_overdue(self, today=None):
        return self.balance_paise > 0 and self.due_on < (today or timezone.localdate())

    def __str__(self):
        return f"#{self.pk} {self.title} · {self.student}"


class InvoiceLine(ValidatedModel):
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="lines")
    head = models.ForeignKey(FeeHead, on_delete=models.PROTECT, null=True, blank=True)
    description = models.CharField(max_length=80)
    amount_paise = models.PositiveIntegerField()

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.CheckConstraint(condition=Q(amount_paise__gt=0), name="invoice_line_positive")
        ]


class Concession(ValidatedModel):
    """A reduction granted on an invoice, with the reason, by an admin."""

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="concessions")
    amount_paise = models.PositiveIntegerField()
    reason = models.CharField(max_length=200)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.CheckConstraint(condition=Q(amount_paise__gt=0), name="concession_positive")
        ]


class PaymentOrder(models.Model):
    """An online checkout started for an invoice. Not money yet: only a provider's confirmed
    capture becomes a Payment (and gets a receipt)."""

    class Status(models.TextChoices):
        CREATED = "created", "Waiting for payment"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"
        REVIEW = "review", "Needs review"

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="orders")
    gateway = models.CharField(max_length=20)
    gateway_order_id = models.CharField(max_length=64, unique=True)
    amount_paise = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="INR")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CREATED)
    # Why a captured payment couldn't be applied automatically (amount, currency, ...).
    problem = models.CharField(max_length=250, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(condition=Q(amount_paise__gt=0), name="order_positive")
        ]

    def __str__(self):
        return f"{self.gateway} {self.gateway_order_id}"


class Payment(ValidatedModel):
    """Money that was really received. Never deleted; never discarded.

    `applied_paise` is what went towards the invoice. Anything above the balance at that moment
    (an online payment that crossed a counter payment, say) is excess, kept for a refund.
    """

    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        UPI = "upi", "UPI at the counter"
        CHEQUE = "cheque", "Cheque"
        ONLINE = "online", "Online"

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payments")
    method = models.CharField(max_length=10, choices=Method.choices)
    amount_paise = models.PositiveIntegerField()
    applied_paise = models.PositiveIntegerField()
    order = models.OneToOneField(
        PaymentOrder, on_delete=models.PROTECT, null=True, blank=True, related_name="payment"
    )
    gateway = models.CharField(max_length=20, blank=True)
    gateway_payment_id = models.CharField(max_length=64, blank=True)
    reference = models.CharField(max_length=60, blank=True, help_text="UPI or cheque reference")
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    paid_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-paid_at", "-pk"]
        constraints = [
            models.CheckConstraint(condition=Q(amount_paise__gt=0), name="payment_positive"),
            models.CheckConstraint(
                condition=Q(applied_paise__lte=F("amount_paise")), name="applied_within_amount"
            ),
            # The same provider payment can never be recorded twice (a repeated webhook).
            models.UniqueConstraint(
                fields=["gateway", "gateway_payment_id"],
                condition=~Q(gateway_payment_id=""),
                name="provider_payment_once",
            ),
        ]

    @property
    def excess_paise(self):
        return self.amount_paise - self.applied_paise


class ReceiptCounter(models.Model):
    """The last receipt number used per branch and year. Locked while a number is taken, inside
    the payment's transaction, so numbers are gapless and never reused."""

    branch = models.ForeignKey(Branch, on_delete=models.PROTECT)
    year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT)
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["branch", "year"], name="one_counter_per_branch_year")
        ]

    def __str__(self):
        return f"{self.branch.receipt_code} {self.year}: {self.last_number}"


class Receipt(models.Model):
    payment = models.OneToOneField(Payment, on_delete=models.PROTECT, related_name="receipt")
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT)
    year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT)
    sequence = models.PositiveIntegerField()
    number = models.CharField(max_length=40, unique=True)
    issued_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-issued_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "year", "sequence"], name="receipt_sequence_once"
            )
        ]

    def __str__(self):
        return self.number
