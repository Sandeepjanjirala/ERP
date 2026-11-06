"""Every write to fees. Each service checks its policy, works inside one transaction, locks the
rows it changes, and writes the activity log."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit.services import audit
from apps.core.jobs import run_after_commit
from apps.students.models import Student

from .gateways import GatewayError, get_gateway, parse_event, payment_event
from .models import (
    Concession,
    FeePlanItem,
    Invoice,
    InvoiceLine,
    Payment,
    PaymentOrder,
    Receipt,
    ReceiptCounter,
    rupees,
)
from .policies import can_collect_fees, can_pay_online, can_set_up_fees
from .tasks import notify_invoices_issued, send_receipt


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


# Payments and receipts -------------------------------------------------------------------------

COUNTER_METHODS = (Payment.Method.CASH, Payment.Method.UPI, Payment.Method.CHEQUE)


def receipt_number(branch, year, sequence):
    """e.g. NORTH/2026-27/00042: branch, academic year, then the sequence."""
    start = year.starts_on.year
    return f"{branch.receipt_code}/{start}-{(start + 1) % 100:02d}/{sequence:05d}"


def _take_receipt_number(branch, year):
    """The next receipt number for the branch and year.

    The counter row is locked until the payment's transaction ends. If the payment rolls back,
    so does the increment: no gaps. Once committed, a number is never handed out again.
    """
    try:
        with transaction.atomic():  # a savepoint: another payment may create the row first
            ReceiptCounter.objects.get_or_create(branch=branch, year=year)
    except IntegrityError:
        pass
    counter = ReceiptCounter.objects.select_for_update().get(branch=branch, year=year)
    counter.last_number += 1
    counter.save(update_fields=["last_number"])
    return counter.last_number


def _apply(invoice, amount_paise, **fields):
    """Record money received against a locked invoice, and issue its receipt.

    Only what the invoice still owes is applied; the rest is kept on the payment as excess for a
    refund. The money is recorded either way: a confirmed payment is never discarded.
    """
    applied = min(amount_paise, invoice.balance_paise)
    payment = Payment.objects.create(
        invoice=invoice, amount_paise=amount_paise, applied_paise=applied, **fields
    )
    if applied:
        invoice.paid_paise += applied
        invoice.status = settle(invoice)
        invoice.version += 1
        invoice.save()
    sequence = _take_receipt_number(invoice.branch, invoice.year)
    Receipt.objects.create(
        payment=payment,
        branch=invoice.branch,
        year=invoice.year,
        sequence=sequence,
        number=receipt_number(invoice.branch, invoice.year, sequence),
    )
    run_after_commit(send_receipt, payment.pk)
    return payment


@transaction.atomic
def record_counter_payment(actor, invoice, amount_paise, method, reference=""):
    """Cash, UPI or a cheque taken at the school office. Never more than the balance."""
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if not can_collect_fees(actor, invoice.branch):
        raise PermissionDenied
    if method not in COUNTER_METHODS:
        raise ValidationError({"method": "Choose cash, UPI or cheque."})
    if method != Payment.Method.CASH and not reference.strip():
        raise ValidationError({"reference": "Enter the UPI or cheque reference."})
    if invoice.balance_paise <= 0:
        raise ValidationError("This invoice has nothing left to pay.")
    if not 0 < amount_paise <= invoice.balance_paise:
        raise ValidationError(
            {"amount_paise": f"Enter an amount up to the balance, {rupees(invoice.balance_paise)}."}
        )
    payment = _apply(
        invoice,
        amount_paise,
        method=method,
        reference=reference.strip(),
        recorded_by=actor,
        paid_at=timezone.now(),
    )
    audit(
        actor,
        invoice.branch,
        "fees.payment.recorded",
        invoice,
        {
            "amount_paise": amount_paise,
            "method": method,
            "reference": reference.strip(),
            "receipt": payment.receipt.number,
        },
    )
    return payment


# Online payments ---------------------------------------------------------------------------


class InvalidSignature(Exception):
    """A webhook that wasn't signed with the provider's secret: ignored, never trusted."""


def start_online_payment(actor, invoice):
    """Ask the provider for a checkout order for the invoice's current balance.

    Deliberately outside a transaction: no database lock is held during the network call.
    """
    invoice = Invoice.objects.get(pk=invoice.pk)
    if not can_pay_online(actor, invoice):
        raise PermissionDenied
    if invoice.balance_paise <= 0:
        raise ValidationError("This invoice has nothing left to pay.")
    gateway = get_gateway()
    order = PaymentOrder.objects.create(
        invoice=invoice,
        gateway=gateway.name,
        gateway_order_id=gateway.create_order(
            invoice.balance_paise, "INR", receipt=f"invoice-{invoice.pk}"
        ),
        amount_paise=invoice.balance_paise,
        currency="INR",
        created_by=actor,
    )
    audit(
        actor,
        invoice.branch,
        "fees.online.started",
        invoice,
        {
            "gateway": gateway.name,
            "order": order.gateway_order_id,
            "amount_paise": order.amount_paise,
        },
    )
    return order


@transaction.atomic
def confirm_online_payment(gateway_name, event):
    """Apply a provider's payment event. Safe to receive any number of times.

    Returns what happened: "recorded", "review", "duplicate", "failed", "ignored" or
    "unknown_order". Captured money is never thrown away: it is recorded (as excess if it is
    more than the balance), or, when it can't be counted as rupees, kept on the order for a
    person to resolve.
    """
    # Lock the order first: a repeated webhook arriving at the same moment waits here.
    order = (
        PaymentOrder.objects.select_for_update()
        .filter(gateway=gateway_name, gateway_order_id=event.order_id)
        .first()
    )
    if order is None:
        return "unknown_order"  # not an order EduNexa created
    if event.kind == "failed":
        if order.status == PaymentOrder.Status.CREATED:
            order.status = PaymentOrder.Status.FAILED
            order.save(update_fields=["status", "updated_at"])
        return "failed"
    if event.kind != "captured" or event.status != "captured":
        return "ignored"
    if (
        Payment.objects.filter(gateway=gateway_name, gateway_payment_id=event.payment_id).exists()
        or order.gateway_payment_id == event.payment_id
    ):
        return "duplicate"

    invoice = Invoice.objects.select_for_update().get(pk=order.invoice_id)
    already_paid = Payment.objects.filter(order=order).exists()
    problems = []
    if event.currency != order.currency:
        problems.append(f"captured in {event.currency}, the order was in {order.currency}")
    if event.amount_paise != order.amount_paise:
        problems.append(
            f"captured {rupees(event.amount_paise)}, the order was for {rupees(order.amount_paise)}"
        )
    if already_paid:
        problems.append("a second payment for an order that was already paid")
    order.gateway_payment_id = event.payment_id
    order.captured_amount_paise = event.amount_paise
    order.captured_currency = event.currency
    order.problem = "; ".join(problems)
    details = {
        "gateway": gateway_name,
        "payment": event.payment_id,
        "amount_paise": event.amount_paise,
        "currency": event.currency,
    }
    if event.currency != order.currency:
        # Money in another currency can't be counted as rupees: keep every detail for review.
        order.status = PaymentOrder.Status.REVIEW
        order.save()
        audit(
            order.created_by,
            invoice.branch,
            "fees.online.review",
            invoice,
            {**details, "problem": order.problem},
        )
        return "review"
    payment = _apply(
        invoice,
        event.amount_paise,
        method=Payment.Method.ONLINE,
        gateway=gateway_name,
        gateway_payment_id=event.payment_id,
        order=None if already_paid else order,
        paid_at=timezone.now(),
    )
    order.status = PaymentOrder.Status.REVIEW if problems else PaymentOrder.Status.PAID
    order.save()
    audit(
        order.created_by,
        invoice.branch,
        "fees.online.captured",
        invoice,
        {
            **details,
            "receipt": payment.receipt.number,
            "excess_paise": payment.excess_paise,
            "problem": order.problem,
        },
    )
    return "review" if problems else "recorded"


def receive_webhook(gateway_name, body, signature):
    """Check a provider's webhook and apply it. InvalidSignature if it wasn't signed by them."""
    gateway = get_gateway(gateway_name)
    if not gateway.verify(body, signature):
        raise InvalidSignature
    return confirm_online_payment(gateway_name, parse_event(body))


def simulate_sandbox_payment(actor, order, outcome):
    """The Sandbox plays the provider: it sends the signed webhook Razorpay would send, so a test
    payment goes through exactly the same checks as a real one."""
    if order.gateway != "sandbox" or not can_pay_online(actor, order.invoice):
        raise PermissionDenied
    gateway = get_gateway("sandbox")
    body = gateway.event_body(order, outcome)
    return receive_webhook(gateway.name, body, gateway.sign(body))


def confirm_checkout(actor, order, payment_id, signature):
    """Razorpay's checkout sent the browser back with a payment id and a signature.

    Nothing from the browser is trusted for the money: the signature proves Razorpay issued that
    payment id for this order, and the amount, currency and status are fetched from Razorpay.
    The webhook may arrive first or later; either way the payment is recorded once.
    """
    if order.gateway != "razorpay" or not can_pay_online(actor, order.invoice):
        raise PermissionDenied
    gateway = get_gateway("razorpay")
    if not payment_id or not gateway.verify_checkout(order.gateway_order_id, payment_id, signature):
        raise InvalidSignature
    data = gateway.fetch_payment(payment_id)  # a network call, outside any transaction
    status = data.get("status") if isinstance(data, dict) else None
    try:
        event = payment_event(
            data, {"captured": "captured", "failed": "failed"}.get(status, "other")
        )
    except ValueError as error:
        raise GatewayError("Razorpay sent a reply EduNexa didn't understand.") from error
    if (event.order_id, event.payment_id) != (order.gateway_order_id, payment_id):
        raise InvalidSignature
    return confirm_online_payment("razorpay", event)
