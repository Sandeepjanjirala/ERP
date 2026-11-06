from django.shortcuts import render
from django.utils import timezone

from apps.accounts.decorators import role_required
from apps.accounts.models import User
from apps.core.pagination import paginate

from .models import Invoice
from .selectors import OPEN, invoices, overdue, search, totals

# Views that show filters: their value and label.
FILTERS = [
    ("open", "Unpaid"),
    ("overdue", "Overdue"),
    ("paid", "Paid"),
    ("cancelled", "Cancelled"),
    ("all", "All"),
]


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
