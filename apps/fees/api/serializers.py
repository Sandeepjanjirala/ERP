"""Money in the API is always whole paise (₹1 = 100 paise), as integers: `amount_paise`."""

from django.urls import reverse
from django.utils import timezone
from rest_framework import serializers

from apps.academics.models import AcademicYear
from apps.academics.selectors import grades
from apps.accounts.api.serializers import UserSummarySerializer
from apps.core.api.fields import ScopedPrimaryKeyField
from apps.organization.selectors import branches

from ..models import (
    Concession,
    FeeHead,
    FeePlan,
    FeePlanItem,
    Invoice,
    InvoiceLine,
    Payment,
    PaymentOrder,
)
from ..services import COUNTER_METHODS


class InvoiceSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.user.display_name", read_only=True)
    admission_number = serializers.CharField(source="student.admission_number", read_only=True)
    grade = serializers.CharField(source="plan.grade.name", allow_null=True, read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    balance_paise = serializers.IntegerField(read_only=True)
    overdue = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            "id",
            "branch",
            "year",
            "student",
            "student_name",
            "admission_number",
            "grade",
            "title",
            "issued_on",
            "due_on",
            "status",
            "status_label",
            "overdue",
            "total_paise",
            "paid_paise",
            "balance_paise",
            "version",
        ]
        read_only_fields = fields

    def get_overdue(self, invoice) -> bool:
        return invoice.is_overdue(timezone.localdate())


class InvoiceLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceLine
        fields = ["id", "head", "description", "amount_paise"]
        read_only_fields = fields


class ConcessionSerializer(serializers.ModelSerializer):
    granted_by = UserSummarySerializer(read_only=True)

    class Meta:
        model = Concession
        fields = ["id", "amount_paise", "reason", "granted_by", "created_at"]
        read_only_fields = fields


class PaymentSerializer(serializers.ModelSerializer):
    method_label = serializers.CharField(source="get_method_display", read_only=True)
    excess_paise = serializers.IntegerField(read_only=True)
    receipt_id = serializers.IntegerField(source="receipt.pk", read_only=True)
    receipt_number = serializers.CharField(source="receipt.number", read_only=True)
    recorded_by = UserSummarySerializer(read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "invoice",
            "method",
            "method_label",
            "amount_paise",
            "applied_paise",
            "excess_paise",
            "reference",
            "gateway",
            "gateway_payment_id",
            "receipt_id",
            "receipt_number",
            "recorded_by",
            "paid_at",
        ]
        read_only_fields = fields


class InvoiceDetailSerializer(InvoiceSerializer):
    """An invoice with its charges, concessions, payments and (cancelled) reason."""

    lines = InvoiceLineSerializer(many=True, read_only=True)
    concessions = ConcessionSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)

    class Meta(InvoiceSerializer.Meta):
        fields = [
            *InvoiceSerializer.Meta.fields,
            "cancel_reason",
            "cancelled_at",
            "lines",
            "concessions",
            "payments",
        ]
        read_only_fields = fields


class CounterPaymentSerializer(serializers.Serializer):
    """Cash, UPI or a cheque taken at the office. UPI and cheques need their `reference`."""

    amount_paise = serializers.IntegerField(min_value=1)
    method = serializers.ChoiceField(choices=[(m.value, m.label) for m in COUNTER_METHODS])
    reference = serializers.CharField(max_length=60, required=False, allow_blank=True, default="")


class ConcessionCreateSerializer(serializers.Serializer):
    amount_paise = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=200)


class CancelSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=250)


class PaymentOrderSerializer(serializers.ModelSerializer):
    """An online checkout. `checkout_url` is the web page that takes the payment."""

    status_label = serializers.CharField(source="get_status_display", read_only=True)
    checkout_url = serializers.SerializerMethodField()

    class Meta:
        model = PaymentOrder
        fields = [
            "id",
            "invoice",
            "gateway",
            "gateway_order_id",
            "amount_paise",
            "currency",
            "status",
            "status_label",
            "gateway_payment_id",
            "captured_amount_paise",
            "captured_currency",
            "problem",
            "created_at",
            "checkout_url",
        ]
        read_only_fields = fields

    def get_checkout_url(self, order) -> str:
        request = self.context.get("request")
        url = reverse("checkout", args=[order.pk])
        return request.build_absolute_uri(url) if request else url


class FeeHeadSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeeHead
        fields = ["id", "branch", "name", "code"]
        read_only_fields = fields


class FeePlanItemSerializer(serializers.ModelSerializer):
    head_name = serializers.CharField(source="head.name", read_only=True)

    class Meta:
        model = FeePlanItem
        fields = ["head", "head_name", "amount_paise"]
        read_only_fields = fields


class FeePlanSerializer(serializers.ModelSerializer):
    """`grade` is the grade's name; `grade_id` the Grade (GET /api/v1/grades/)."""

    grade = serializers.CharField(source="grade.name", read_only=True)
    grade_id = serializers.IntegerField(read_only=True)
    items = FeePlanItemSerializer(many=True, read_only=True)
    total_paise = serializers.SerializerMethodField()

    class Meta:
        model = FeePlan
        fields = ["id", "branch", "year", "grade", "grade_id", "items", "total_paise"]
        read_only_fields = fields

    def get_total_paise(self, plan) -> int:
        return sum(item.amount_paise for item in plan.items.all())


class IssueInvoicesSerializer(serializers.Serializer):
    """Invoice every student now in the plan's grade. The same title again skips students who
    already have it, so a retried request is harmless."""

    title = serializers.CharField(max_length=80)
    due_on = serializers.DateField()

    def validate_due_on(self, due_on):
        if due_on < timezone.localdate():
            raise serializers.ValidationError("The due date can't be before today.")
        return due_on


class IssueResultSerializer(serializers.Serializer):
    created = serializers.IntegerField()
    skipped = serializers.IntegerField()
    invoices = serializers.ListField(child=serializers.IntegerField())


class FeeHeadWriteSerializer(serializers.ModelSerializer):
    branch = ScopedPrimaryKeyField(branches)

    class Meta:
        model = FeeHead
        fields = ["branch", "name", "code"]
        validators = []


class FeeHeadUpdateSerializer(FeeHeadWriteSerializer):
    branch = serializers.PrimaryKeyRelatedField(read_only=True)


class FeePlanItemWriteSerializer(serializers.Serializer):
    head = serializers.IntegerField(help_text="A fee head of the plan's branch")
    amount_paise = serializers.IntegerField(min_value=0, help_text="0 leaves the head out")


class FeePlanWriteSerializer(serializers.Serializer):
    """A new plan: what one student of a grade pays in a year, one amount per fee head."""

    branch = ScopedPrimaryKeyField(branches)
    year = serializers.PrimaryKeyRelatedField(queryset=AcademicYear.objects.all())
    grade_id = ScopedPrimaryKeyField(grades)
    items = FeePlanItemWriteSerializer(many=True)


class FeePlanUpdateSerializer(serializers.Serializer):
    """New amounts for a plan. Its branch, year and grade are fixed; invoices already issued
    keep their own amounts."""

    items = FeePlanItemWriteSerializer(many=True)


class CollectionsQuerySerializer(serializers.Serializer):
    """The collection report's period (default: this month so far) and branch."""

    start = serializers.DateField(required=False, help_text="First day (default: the 1st)")
    end = serializers.DateField(required=False, help_text="Last day (default: today)")
    branch = serializers.IntegerField(required=False, help_text="Branch id (404 outside scope)")

    def validate(self, attrs):
        today = timezone.localdate()
        attrs.setdefault("start", today.replace(day=1))
        attrs.setdefault("end", today)
        if attrs["start"] > attrs["end"]:
            raise serializers.ValidationError(
                {"start": "The start date must be on or before the end date."}
            )
        return attrs


class MethodTotalSerializer(serializers.Serializer):
    method = serializers.CharField()
    received_paise = serializers.IntegerField()


class CollectionsSerializer(serializers.Serializer):
    start = serializers.DateField()
    end = serializers.DateField()
    count = serializers.IntegerField(help_text="Payments received")
    received_paise = serializers.IntegerField()
    applied_paise = serializers.IntegerField(help_text="Applied to invoices")
    excess_paise = serializers.IntegerField(help_text="Held for refund")
    by_method = MethodTotalSerializer(many=True)
