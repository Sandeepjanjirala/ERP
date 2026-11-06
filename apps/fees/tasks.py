from celery import shared_task
from django.urls import reverse

from apps.communication.models import Notification
from apps.communication.services import notify
from apps.students.models import Student
from apps.students.selectors import family

from .models import Invoice, rupees


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
