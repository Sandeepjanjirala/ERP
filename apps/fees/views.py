from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.decorators import role_required
from apps.accounts.models import User
from apps.core.exceptions import error_text
from apps.core.pagination import paginate
from apps.organization.selectors import branches

from .forms import (
    CancelForm,
    ConcessionForm,
    CounterPaymentForm,
    FeeHeadForm,
    FeePlanForm,
    IssueInvoicesForm,
)
from .gateways import GatewayError
from .models import FeeHead, FeePlan, Invoice, PaymentOrder
from .pdf import receipt_filename, render_receipt
from .policies import can_collect_fees, can_pay_online, can_set_up_fees
from .selectors import (
    OPEN,
    excess_payments,
    fee_heads,
    fee_plans,
    invoices,
    orders_for_review,
    overdue,
    payment_orders,
    receipts,
    search,
    totals,
)
from .services import (
    InvalidSignature,
    cancel_invoice,
    confirm_checkout,
    grant_concession,
    issue_invoices,
    record_counter_payment,
    save_fee_head,
    save_fee_plan,
    simulate_sandbox_payment,
    start_online_payment,
)

# Views that show filters: their value and label.
FILTERS = [
    ("open", "Unpaid"),
    ("overdue", "Overdue"),
    ("paid", "Paid"),
    ("cancelled", "Cancelled"),
    ("all", "All"),
]

# What the online payment outcomes mean to the person who just paid.
OUTCOMES = {
    "recorded": (messages.SUCCESS, "Payment received. The receipt has been emailed to you."),
    "duplicate": (messages.SUCCESS, "This payment was already recorded."),
    "review": (
        messages.WARNING,
        "Your payment was received but needs a check by the school office. "
        "It is safe: nothing more needs to be paid for it.",
    ),
    "failed": (messages.ERROR, "The payment did not go through. No money was taken."),
    "ignored": (
        messages.INFO,
        "Your payment is being confirmed. The receipt will follow as soon as it is.",
    ),
}


def _add_errors(form, exc):
    """Show a service's ValidationError on the form, next to the field it is about."""
    names = {"amount_paise": "amount"}
    if hasattr(exc, "error_dict"):
        for field, errors in exc.message_dict.items():
            field = names.get(field, field)
            form.add_error(field if field in form.fields else None, errors)
    else:
        form.add_error(None, exc.messages)


def _announce(request, outcome):
    level, text = OUTCOMES.get(outcome, OUTCOMES["ignored"])
    messages.add_message(request, level, text)


# Invoices ----------------------------------------------------------------------------------


@role_required(*User.FINANCE, User.Role.PARENT)
def invoice_list(request):
    """Finance staff: the branch's invoices. Parents: their children's."""
    today = timezone.localdate()
    shown = request.GET.get("show", "open")
    qs = invoices(request.user)
    scoped_totals = totals(qs)
    if shown == "open":
        qs = qs.filter(status__in=OPEN)
    elif shown == "overdue":
        qs = overdue(qs, today)
    elif shown in (Invoice.Status.PAID, Invoice.Status.CANCELLED):
        qs = qs.filter(status=shown)
    query = request.GET.get("q", "")
    qs = search(qs, query).order_by("due_on", "pk")
    page_obj = paginate(request, qs)
    for invoice in page_obj:
        invoice.overdue = invoice.is_overdue(today)
    return render(
        request,
        "fees/invoice_list.html",
        {
            "title": "Fees",
            "page_obj": page_obj,
            "filters": FILTERS,
            "shown": shown,
            "query": query,
            "totals": scoped_totals,
            "overdue_count": overdue(invoices(request.user), today).count(),
        },
    )


def _detail(request, invoice, **forms):
    """The invoice page, with any form that failed shown again with its errors."""
    user = request.user
    payments = list(invoice.payments.select_related("receipt", "recorded_by").order_by("pk"))
    can_adjust = can_set_up_fees(user, invoice.branch)
    return render(
        request,
        "fees/invoice_detail.html",
        {
            "title": f"Invoice #{invoice.pk}",
            "invoice": invoice,
            "overdue": invoice.is_overdue(),
            "lines": invoice.lines.all(),
            "concessions": invoice.concessions.select_related("granted_by"),
            "payments": payments,
            "orders": invoice.orders.all() if user.role in User.FINANCE else (),
            "can_collect": can_collect_fees(user, invoice.branch) and invoice.balance_paise > 0,
            "can_concede": can_adjust and invoice.status in OPEN,
            "can_cancel": can_adjust and invoice.status == Invoice.Status.ISSUED and not payments,
            "can_pay": can_pay_online(user, invoice) and invoice.balance_paise > 0,
            "payment_form": forms.get("payment_form") or CounterPaymentForm(),
            "concession_form": forms.get("concession_form") or ConcessionForm(),
            "cancel_form": forms.get("cancel_form") or CancelForm(),
        },
    )


def _invoice(request, pk):
    return get_object_or_404(
        invoices(request.user).select_related("cancelled_by", "issued_by"), pk=pk
    )


@role_required(*User.FINANCE, User.Role.PARENT)
def invoice_detail(request, pk):
    return _detail(request, _invoice(request, pk))


@require_POST
@role_required(*User.FINANCE)
def payment_record(request, pk):
    invoice = _invoice(request, pk)
    form = CounterPaymentForm(request.POST)
    if form.is_valid():
        data = form.cleaned_data
        try:
            payment = record_counter_payment(
                request.user, invoice, data["amount"], data["method"], data["reference"]
            )
        except ValidationError as exc:
            _add_errors(form, exc)
        else:
            messages.success(request, f"Payment recorded. Receipt {payment.receipt.number}.")
            return redirect("invoice_detail", invoice.pk)
    return _detail(request, invoice, payment_form=form)


@require_POST
@role_required(*User.MANAGERS)
def concession_grant(request, pk):
    invoice = _invoice(request, pk)
    form = ConcessionForm(request.POST)
    if form.is_valid():
        try:
            grant_concession(
                request.user, invoice, form.cleaned_data["amount"], form.cleaned_data["reason"]
            )
        except ValidationError as exc:
            _add_errors(form, exc)
        else:
            messages.success(request, "Concession granted. The balance has been reduced.")
            return redirect("invoice_detail", invoice.pk)
    return _detail(request, invoice, concession_form=form)


@require_POST
@role_required(*User.MANAGERS)
def invoice_cancel(request, pk):
    invoice = _invoice(request, pk)
    form = CancelForm(request.POST)
    if form.is_valid():
        try:
            cancel_invoice(request.user, invoice, form.cleaned_data["reason"])
        except ValidationError as exc:
            _add_errors(form, exc)
        else:
            messages.success(request, "Invoice cancelled.")
            return redirect("invoice_detail", invoice.pk)
    return _detail(request, invoice, cancel_form=form)


@role_required(*User.FINANCE, User.Role.PARENT)
def receipt_pdf(request, pk):
    receipt = get_object_or_404(receipts(request.user), pk=pk)
    response = HttpResponse(render_receipt(receipt.payment), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{receipt_filename(receipt.payment)}"'
    return response


# Paying online -----------------------------------------------------------------------------


@require_POST
@role_required(User.Role.PARENT)
def pay_online(request, pk):
    invoice = _invoice(request, pk)
    try:
        order = start_online_payment(request.user, invoice)
    except (ValidationError, GatewayError) as exc:
        messages.error(request, "; ".join(getattr(exc, "messages", [str(exc)])))
        return redirect("invoice_detail", invoice.pk)
    return redirect("checkout", order.pk)


def _open_order(request, pk):
    return get_object_or_404(
        payment_orders(request.user).filter(
            status__in=(PaymentOrder.Status.CREATED, PaymentOrder.Status.FAILED)
        ),
        pk=pk,
    )


@role_required(User.Role.PARENT)
def checkout(request, pk):
    order = _open_order(request, pk)
    invoice = order.invoice
    context = {"title": "Pay fees online", "order": order, "invoice": invoice}
    if order.gateway == "sandbox":
        return render(request, "fees/checkout_sandbox.html", context)
    response = render(
        request,
        "fees/checkout_razorpay.html",
        {
            **context,
            "checkout": {
                "key": settings.RAZORPAY_KEY_ID,
                "order_id": order.gateway_order_id,
                "amount": order.amount_paise,
                "currency": order.currency,
                "name": invoice.branch.name,
                "description": f"#{invoice.pk} {invoice.title}",
                "prefill": {"name": request.user.display_name, "email": request.user.email},
            },
        },
    )
    # Razorpay's checkout script and its payment window come from razorpay.com.
    response.csp_add = {
        "script-src": ["https://checkout.razorpay.com"],
        "frame-src": ["https://api.razorpay.com", "https://checkout.razorpay.com"],
        "connect-src": ["https://api.razorpay.com", "https://lumberjack.razorpay.com"],
        "img-src": ["https://cdn.razorpay.com"],
    }
    return response


@require_POST
@role_required(User.Role.PARENT)
def sandbox_pay(request, pk):
    order = _open_order(request, pk)
    outcome = "captured" if request.POST.get("outcome") == "captured" else "failed"
    _announce(request, simulate_sandbox_payment(request.user, order, outcome))
    return redirect("invoice_detail", order.invoice_id)


@require_POST
@role_required(User.Role.PARENT)
def razorpay_callback(request, pk):
    """Where Razorpay's checkout sends the browser after a payment. The signature proves the
    details came from Razorpay; the amount and status are then fetched from Razorpay itself."""
    order = get_object_or_404(payment_orders(request.user).filter(gateway="razorpay"), pk=pk)
    try:
        outcome = confirm_checkout(
            request.user,
            order,
            request.POST.get("razorpay_payment_id", ""),
            request.POST.get("razorpay_signature", ""),
        )
    except InvalidSignature:
        messages.error(request, "That payment could not be verified. No receipt was issued.")
    except GatewayError as exc:
        # The webhook will still record the payment if it went through.
        messages.warning(request, f"{exc} If you paid, the receipt will follow shortly.")
    else:
        _announce(request, outcome)
    return redirect("invoice_detail", order.invoice_id)


# Fee setup ---------------------------------------------------------------------------------


@role_required(*User.FINANCE)
def fee_setup(request):
    """Fee heads and plans per branch. Admins change them; finance staff issue invoices."""
    heads, plans = list(fee_heads(request.user)), list(fee_plans(request.user))
    sections = []
    for branch in branches(request.user):
        branch_plans = [plan for plan in plans if plan.branch_id == branch.pk]
        for plan in branch_plans:
            plan.total_paise = sum(item.amount_paise for item in plan.items.all())
            plan.can_issue = can_collect_fees(request.user, branch)
        sections.append(
            {
                "branch": branch,
                "heads": [head for head in heads if head.branch_id == branch.pk],
                "plans": branch_plans,
                "can_set_up": can_set_up_fees(request.user, branch),
            }
        )
    return render(request, "fees/setup.html", {"title": "Fee setup", "sections": sections})


def _form_page(request, form, title, description):
    return render(
        request, "form_page.html", {"title": title, "form": form, "description": description}
    )


@role_required(*User.MANAGERS)
def fee_head_create(request, branch_pk):
    branch = get_object_or_404(branches(request.user), pk=branch_pk)
    form = FeeHeadForm(request.POST or None, instance=FeeHead(branch=branch))
    if request.method == "POST" and form.is_valid():
        try:
            save_fee_head(request.user, form.save(commit=False))
        except (ValidationError, IntegrityError) as exc:
            form.add_error(None, error_text(exc, "This branch already has a fee with that code."))
        else:
            messages.success(request, "Fee head added.")
            return redirect("fee_setup")
    return _form_page(request, form, "Add a fee head", f"A kind of charge at {branch.name}.")


def _plan_form(request, plan, branch):
    heads = fee_heads(request.user).filter(branch=branch)
    form = FeePlanForm(request.POST or None, instance=plan, branch=branch, heads=heads)
    if request.method == "POST" and form.is_valid():
        try:
            save_fee_plan(request.user, form.save(commit=False), form.amounts())
        except (ValidationError, IntegrityError) as exc:
            form.add_error(None, error_text(exc, "This grade already has a plan for that year."))
        else:
            messages.success(request, "Fee plan saved. Invoices already issued are unchanged.")
            return redirect("fee_setup")
    return _form_page(
        request,
        form,
        "Edit fee plan" if plan.pk else "Add a fee plan",
        f"What one student of the grade pays in the year at {branch.name}. "
        "Changes apply to invoices issued from now on.",
    )


@role_required(*User.MANAGERS)
def fee_plan_create(request, branch_pk):
    branch = get_object_or_404(branches(request.user), pk=branch_pk)
    return _plan_form(request, FeePlan(branch=branch), branch)


@role_required(*User.MANAGERS)
def fee_plan_edit(request, pk):
    plan = get_object_or_404(fee_plans(request.user), pk=pk)
    return _plan_form(request, plan, plan.branch)


@role_required(*User.FINANCE)
def invoices_issue(request, pk):
    plan = get_object_or_404(fee_plans(request.user), pk=pk)
    form = IssueInvoicesForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            created, skipped = issue_invoices(
                request.user, plan, form.cleaned_data["title"], form.cleaned_data["due_on"]
            )
        except ValidationError as exc:
            _add_errors(form, exc)
        else:
            text = f"{len(created)} invoices issued. Families are being notified."
            if skipped:
                text += f" {skipped} students already had this invoice and were skipped."
            messages.success(request, text)
            return redirect("fees")
    return _form_page(
        request,
        form,
        f"Issue invoices: {plan}",
        f"One invoice for every student now in {plan.grade} at {plan.branch.name}. "
        "Issuing the same title again skips students who already have it.",
    )


# Payments to check -------------------------------------------------------------------------


@role_required(*User.FINANCE)
def payment_review(request):
    """Online payments that need a person, and money held beyond an invoice's balance."""
    return render(
        request,
        "fees/review.html",
        {
            "title": "Payments to check",
            "orders": orders_for_review(request.user),
            "excess": excess_payments(request.user),
        },
    )
