from celery import shared_task
from django.urls import reverse

from apps.accounts.models import User
from apps.communication.models import Notification
from apps.communication.services import notify
from apps.students.models import Student
from apps.students.selectors import family

from .models import Invoice, Payment, rupees
from .pdf import receipt_filename, render_receipt


@shared_task
def notify_invoices_issued(invoice_ids):
    """Tell each invoiced student's family about the new invoice. Safe to run twice."""
    sent = 0
    for invoice in Invoice.objects.filter(pk__in=invoice_ids).select_related("student__user"):
        sent += notify(
            family(Student.objects.filter(pk=invoice.student_id)),
            Notification.Kind.FEES,
            f"invoice:{invoice.pk}",
            f"New fee invoice: {invoice.title}",
            f"{rupees(invoice.total_paise)} for {invoice.student.user.display_name}, "
            f"due {invoice.due_on:%d %b %Y}.",
            url=reverse("fees"),
            email=True,
        )
    return sent


@shared_task
def send_receipt(payment_id):
    """Notify the student's guardians of a payment, with the receipt PDF attached by email.
    Safe to run twice: one notification and email per guardian per payment."""
    payment = Payment.objects.select_related(
        "receipt", "invoice__student__user", "invoice__branch"
    ).get(pk=payment_id)
    invoice = payment.invoice
    guardians = User.objects.filter(
        guardian_profile__child_links__student=invoice.student, is_active=True
    )
    return notify(
        guardians,
        Notification.Kind.FEES,
        f"receipt:{payment.pk}",
        f"Payment received: {rupees(payment.amount_paise)}",
        f"Receipt {payment.receipt.number} for {invoice.student.user.display_name}, "
        f"{invoice.title}.",
        url=reverse("fees"),
        email=True,
        attachments=[(receipt_filename(payment), render_receipt(payment), "application/pdf")],
    )
