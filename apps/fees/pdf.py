"""The fee receipt PDF. Layout helpers, letterhead and footer: apps/core/pdf.py."""

from apps.core.pdf import Paragraph, Spacer, escape, letterhead, mm, render, styles, table
from apps.organization.selectors import school_name

from .models import rupees


def balance_after(payment):
    """What the invoice still owed right after this payment (later payments ignored)."""
    applied_so_far = sum(
        p.applied_paise for p in payment.invoice.payments.all() if p.pk <= payment.pk
    )
    return max(payment.invoice.total_paise - applied_so_far, 0)


def receipt_rows(payment):
    invoice, receipt = payment.invoice, payment.receipt
    method = payment.get_method_display()
    if payment.reference:
        method = f"{method} ({payment.reference})"
    rows = [
        ["Receipt number", receipt.number],
        ["Date", f"{payment.paid_at:%d %b %Y}"],
        ["Student", invoice.student.user.display_name],
        ["Admission number", invoice.student.admission_number],
        ["For", f"#{invoice.pk} {invoice.title} ({rupees(invoice.total_paise)})"],
        ["Paid by", method],
        ["Amount received", rupees(payment.amount_paise)],
        ["Balance after this payment", rupees(balance_after(payment))],
    ]
    if payment.excess_paise:
        rows.append(["Held for refund", rupees(payment.excess_paise)])
    return rows


def render_receipt(payment):
    branch = payment.invoice.branch
    story = [
        *letterhead(school_name(), f"{branch.name} · Fee receipt"),
        table(receipt_rows(payment), [55 * mm, 115 * mm]),
        Spacer(1, 6 * mm),
        Paragraph(
            escape("This receipt was issued electronically and needs no signature."),
            styles()["BodyText"],
        ),
    ]
    return render(story, f"Receipt {payment.receipt.number}", school_name())


def receipt_filename(payment):
    return f"receipt-{payment.receipt.number.replace('/', '-')}.pdf"
