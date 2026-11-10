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


def statement_rows(invoices):
    """The statement table: a header row, one row per invoice, then the totals."""
    rows = [["Invoice", "For", "Issued", "Due", "Status", "Amount", "Paid", "Balance"]]
    billed = paid = 0
    for invoice in invoices:
        cancelled = invoice.status == invoice.Status.CANCELLED
        balance = 0 if cancelled else invoice.total_paise - invoice.paid_paise
        rows.append(
            [
                f"#{invoice.pk}",
                invoice.title,
                f"{invoice.issued_on:%d %b %Y}",
                f"{invoice.due_on:%d %b %Y}",
                invoice.get_status_display(),
                rupees(invoice.total_paise),
                rupees(invoice.paid_paise),
                rupees(balance),
            ]
        )
        if not cancelled:
            billed += invoice.total_paise
            paid += invoice.paid_paise
    rows.append(
        [
            "",
            "Total (cancelled invoices excluded)",
            "",
            "",
            "",
            rupees(billed),
            rupees(paid),
            rupees(billed - paid),
        ]
    )
    return rows


def render_statement(student, invoices):
    """Every invoice a student has had, with what was paid and what is still owed, as PDF bytes."""
    sheet = styles()
    story = [
        *letterhead(school_name(), f"{student.user.branch.name} · Fee statement"),
        table(
            [
                ["Student", student.user.display_name],
                ["Admission number", student.admission_number],
            ],
            [45 * mm, 125 * mm],
        ),
        Spacer(1, 6 * mm),
        table(
            statement_rows(invoices),
            [14 * mm, 44 * mm, 20 * mm, 20 * mm, 18 * mm, 20 * mm, 18 * mm, 20 * mm],
        ),
        Spacer(1, 6 * mm),
        Paragraph(
            escape("This statement was issued electronically and needs no signature."),
            sheet["BodyText"],
        ),
    ]
    return render(story, f"Fee statement: {student.user.display_name}", school_name())
