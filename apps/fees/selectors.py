"""Read queries for fees, limited to what the user may see."""

from django.db.models import F, Q, Sum
from django.utils import timezone

from apps.accounts.models import User
from apps.organization.selectors import branches

from .models import FeeHead, FeePlan, Invoice, Payment, PaymentOrder, Receipt

OPEN = (Invoice.Status.ISSUED, Invoice.Status.PARTLY_PAID)


def invoices(user):
    """Finance staff: their branch. Parents: their children's. Nobody else sees fees."""
    qs = Invoice.objects.select_related("student__user", "branch", "year", "plan")
    if user.role in User.FINANCE:
        return qs.filter(branch__in=branches(user))
    if user.is_parent:
        return qs.filter(student__guardian_links__guardian__user=user)
    return qs.none()


def overdue(qs, today=None):
    """Invoices past their due date with money still owed. Computed, never stored."""
    return qs.filter(status__in=OPEN, due_on__lt=today or timezone.localdate())


def fee_heads(user):
    if user.role not in User.FINANCE:
        return FeeHead.objects.none()
    return FeeHead.objects.filter(branch__in=branches(user)).select_related("branch")


def fee_plans(user):
    if user.role not in User.FINANCE:
        return FeePlan.objects.none()
    return (
        FeePlan.objects.filter(branch__in=branches(user))
        .select_related("branch", "year")
        .prefetch_related("items__head")
    )


def payments(user):
    return Payment.objects.filter(invoice__in=invoices(user)).select_related(
        "invoice__student__user", "invoice__branch", "recorded_by", "receipt"
    )


def receipts(user):
    return Receipt.objects.filter(payment__invoice__in=invoices(user)).select_related(
        "payment__invoice__student__user", "branch", "year"
    )


def orders_for_review(user):
    """Captured online payments that could not be applied automatically, and excess money."""
    if user.role not in User.FINANCE:
        return PaymentOrder.objects.none()
    return PaymentOrder.objects.filter(
        invoice__branch__in=branches(user), status=PaymentOrder.Status.REVIEW
    ).select_related("invoice__student__user")


def excess_payments(user):
    """Payments with money beyond the invoice balance: to be refunded by hand."""
    if user.role not in User.FINANCE:
        return Payment.objects.none()
    return payments(user).filter(amount_paise__gt=F("applied_paise"))


def totals(qs):
    """Billed, collected and outstanding for a set of invoices (cancelled ones excluded)."""
    live = qs.exclude(status=Invoice.Status.CANCELLED)
    sums = live.aggregate(billed=Sum("total_paise"), collected=Sum("paid_paise"))
    billed, collected = sums["billed"] or 0, sums["collected"] or 0
    return {"billed": billed, "collected": collected, "outstanding": billed - collected}


def search(qs, text):
    """Match a student's name or admission number, or an invoice number (#42 or 42)."""
    text = text.strip().lstrip("#")
    if not text:
        return qs
    condition = (
        Q(student__user__first_name__icontains=text)
        | Q(student__user__last_name__icontains=text)
        | Q(student__admission_number__icontains=text)
    )
    if text.isdigit():
        condition |= Q(pk=int(text))
    return qs.filter(condition)
