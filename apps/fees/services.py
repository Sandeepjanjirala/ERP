"""Every write to fees. Each service checks its policy, works inside one transaction, locks the
rows it changes, and writes the activity log."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit.services import audit
from apps.core.jobs import run_after_commit
from apps.students.models import Student

from .models import Concession, FeePlanItem, Invoice, InvoiceLine, rupees
from .policies import can_collect_fees, can_set_up_fees
from .tasks import notify_invoices_issued


def settle(invoice):
    """The status that follows from what is billed and paid (cancelled stays cancelled)."""
    if invoice.status == Invoice.Status.CANCELLED:
        return invoice.status
    if invoice.paid_paise >= invoice.total_paise:
        return Invoice.Status.PAID
    if invoice.paid_paise:
        return Invoice.Status.PARTLY_PAID
    return Invoice.Status.ISSUED


# Fee setup ---------------------------------------------------------------------------------


@transaction.atomic
def save_fee_head(actor, head):
    if not can_set_up_fees(actor, head.branch):
        raise PermissionDenied
    head.save()
    audit(actor, head.branch, "fees.head.saved", head)
    return head


@transaction.atomic
def save_fee_plan(actor, plan, amounts):
    """Create or change a plan; `amounts` maps each fee head to paise (0 or missing: not charged).

    Invoices already issued keep their own copy of the lines, so changing a plan never changes
    what someone already owes.
    """
    if not can_set_up_fees(actor, plan.branch):
        raise PermissionDenied
    amounts = {head: paise for head, paise in amounts.items() if paise}
    if not amounts:
        raise ValidationError("A plan needs at least one fee.")
    before = {}
    if plan.pk:
        before = {item.head.name: item.amount_paise for item in plan.items.select_related("head")}
    plan.save()
    plan.items.exclude(head__in=amounts).delete()
    for head, paise in amounts.items():
        FeePlanItem.objects.update_or_create(plan=plan, head=head, defaults={"amount_paise": paise})
    audit(
        actor,
        plan.branch,
        "fees.plan.saved",
        plan,
        {"before": before, "after": {head.name: paise for head, paise in amounts.items()}},
    )
    return plan


# Invoices ----------------------------------------------------------------------------------


@transaction.atomic
def issue_invoices(actor, plan, title, due_on, issued_on=None):
    """Invoice every student currently in a classroom of the plan's grade.

    Students who already have this plan's invoice with the same title are skipped, so issuing
    twice is harmless. Returns (invoices created, students skipped).
    """
    if not can_collect_fees(actor, plan.branch):
        raise PermissionDenied
    issued_on = issued_on or timezone.localdate()
    items = list(plan.items.select_related("head"))
    if not items:
        raise ValidationError("This plan has no fees to invoice.")
    pupils = Student.objects.filter(
        Q(enrollments__left_on__isnull=True) | Q(enrollments__left_on__gte=issued_on),
        enrollments__classroom__branch=plan.branch,
        enrollments__classroom__year=plan.year,
        enrollments__classroom__grade=plan.grade,
    ).distinct()
    already = set(
        Invoice.objects.filter(plan=plan, title=title).values_list("student_id", flat=True)
    )
    created = []
    for student in pupils.exclude(pk__in=already):
        invoice = Invoice.objects.create(
            branch=plan.branch,
            year=plan.year,
            student=student,
            plan=plan,
            title=title,
            issued_on=issued_on,
            due_on=due_on,
            total_paise=sum(item.amount_paise for item in items),
            issued_by=actor,
        )
        InvoiceLine.objects.bulk_create(
            InvoiceLine(
                invoice=invoice,
                head=item.head,
                description=item.head.name,
                amount_paise=item.amount_paise,
            )
            for item in items
        )
        created.append(invoice)
    audit(
        actor,
        plan.branch,
        "fees.invoices.issued",
        f"{plan} · {title}",
        {"created": len(created), "skipped": len(already), "due_on": due_on.isoformat()},
    )
    if created:
        run_after_commit(notify_invoices_issued, [invoice.pk for invoice in created])
    return created, len(already)


@transaction.atomic
def grant_concession(actor, invoice, amount_paise, reason):
    """Reduce what is owed, with a reason. It can't go below what has already been paid."""
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if not can_set_up_fees(actor, invoice.branch):
        raise PermissionDenied
    if invoice.status not in (Invoice.Status.ISSUED, Invoice.Status.PARTLY_PAID):
        raise ValidationError("Concessions are only for invoices with money still owed.")
    if not reason.strip():
        raise ValidationError({"reason": "Give the reason for the concession."})
    if not 0 < amount_paise <= invoice.balance_paise:
        raise ValidationError(
            {"amount_paise": f"Enter an amount up to the balance, {rupees(invoice.balance_paise)}."}
        )
    before = invoice.total_paise
    Concession.objects.create(
        invoice=invoice, amount_paise=amount_paise, reason=reason, granted_by=actor
    )
    invoice.total_paise -= amount_paise
    invoice.status = settle(invoice)
    invoice.version += 1
    invoice.save()
    audit(
        actor,
        invoice.branch,
        "fees.concession.granted",
        invoice,
        {
            "amount_paise": amount_paise,
            "reason": reason,
            "total_before": before,
            "total_after": invoice.total_paise,
        },
    )
    return invoice


@transaction.atomic
def cancel_invoice(actor, invoice, reason):
    """Cancel an invoice issued by mistake. Only while nothing at all has been paid on it."""
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if not can_set_up_fees(actor, invoice.branch):
        raise PermissionDenied
    if invoice.status != Invoice.Status.ISSUED or invoice.payments.exists():
        raise ValidationError("Only invoices with no payments can be cancelled.")
    if not reason.strip():
        raise ValidationError({"reason": "Give the reason for cancelling."})
    invoice.status = Invoice.Status.CANCELLED
    invoice.cancelled_by, invoice.cancelled_at, invoice.cancel_reason = (
        actor,
        timezone.now(),
        reason,
    )
    invoice.version += 1
    invoice.save()
    audit(actor, invoice.branch, "fees.invoice.cancelled", invoice, {"reason": reason})
    return invoice
