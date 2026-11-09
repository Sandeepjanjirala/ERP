import django_filters
from django.db.models import F
from django.utils import timezone

from ..models import Invoice, Payment, PaymentOrder
from ..selectors import overdue, search

# Ids are plain numbers filtered inside the caller's own scope: an id outside it simply matches
# nothing, rather than an "invalid choice" error that would reveal the record exists.


class InvoiceFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(choices=Invoice.Status.choices)
    student = django_filters.NumberFilter()
    year = django_filters.NumberFilter()
    overdue = django_filters.BooleanFilter(method="filter_overdue", label="Past due, still owed")
    q = django_filters.CharFilter(
        method="filter_search", label="Student name, admission number or invoice number"
    )

    class Meta:
        model = Invoice
        fields = ["status", "student", "year", "overdue", "q"]

    def filter_overdue(self, queryset, name, value):
        late = overdue(queryset, timezone.localdate())
        return late if value else queryset.exclude(pk__in=late.values("pk"))

    def filter_search(self, queryset, name, value):
        return search(queryset, value)


class PaymentFilter(django_filters.FilterSet):
    invoice = django_filters.NumberFilter()
    method = django_filters.ChoiceFilter(choices=Payment.Method.choices)
    excess = django_filters.BooleanFilter(method="filter_excess", label="Money held for refund")

    class Meta:
        model = Payment
        fields = ["invoice", "method", "excess"]

    def filter_excess(self, queryset, name, value):
        held = queryset.filter(amount_paise__gt=F("applied_paise"))
        return held if value else queryset.exclude(pk__in=held.values("pk"))


class PaymentOrderFilter(django_filters.FilterSet):
    invoice = django_filters.NumberFilter()
    status = django_filters.ChoiceFilter(choices=PaymentOrder.Status.choices)

    class Meta:
        model = PaymentOrder
        fields = ["invoice", "status"]
