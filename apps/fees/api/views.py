from django.db.models import Prefetch
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import generics, mixins, renderers, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.core.api.permissions import role_in
from apps.core.api.renderers import CSVRenderer, PDFRenderer
from apps.organization.selectors import selected_branch

from ..gateways import GATEWAYS, GatewayError
from ..models import FeeHead, FeePlan, Invoice, Payment, PaymentOrder
from ..pdf import receipt_filename, render_receipt
from ..selectors import (
    collection_totals,
    collections,
    fee_heads,
    fee_plans,
    invoices,
    payment_orders,
    payments,
    receipts,
)
from ..services import (
    InvalidSignature,
    cancel_invoice,
    export_collections_csv,
    grant_concession,
    issue_invoices,
    receive_webhook,
    record_counter_payment,
    save_fee_head,
    save_fee_plan,
    start_online_payment,
)
from .filters import InvoiceFilter, PaymentFilter, PaymentOrderFilter
from .serializers import (
    CancelSerializer,
    CollectionsQuerySerializer,
    CollectionsSerializer,
    ConcessionCreateSerializer,
    CounterPaymentSerializer,
    FeeHeadSerializer,
    FeeHeadUpdateSerializer,
    FeeHeadWriteSerializer,
    FeePlanSerializer,
    FeePlanUpdateSerializer,
    FeePlanWriteSerializer,
    InvoiceDetailSerializer,
    InvoiceSerializer,
    IssueInvoicesSerializer,
    IssueResultSerializer,
    PaymentOrderSerializer,
    PaymentSerializer,
)

FEES = role_in(*User.FINANCE, User.Role.PARENT)


class InvoiceViewSet(viewsets.ReadOnlyModelViewSet):
    """Fee invoices. Finance staff see their branch's; parents see their children's.

    Amounts are whole paise. `balance_paise` is what is still owed; `overdue` is computed from
    the due date. Every action below checks its own rule again in the service.
    """

    queryset = Invoice.objects.none()  # for the schema
    filterset_class = InvoiceFilter
    ordering_fields = ["due_on", "issued_on", "total_paise"]

    def get_queryset(self):
        qs = invoices(self.request.user)
        if self.action == "list":
            return qs
        return qs.prefetch_related(
            "lines",
            "concessions__granted_by",
            Prefetch(
                "payments",
                queryset=Payment.objects.select_related("receipt", "recorded_by").order_by("pk"),
            ),
        )

    def get_permissions(self):
        roles = {
            "payment": User.FINANCE,
            "concession": User.MANAGERS,
            "cancel": User.MANAGERS,
            "pay_online": (User.Role.PARENT,),
        }.get(self.action)
        return [role_in(*roles)()] if roles else [FEES()]

    def get_serializer_class(self):
        return {
            "list": InvoiceSerializer,
            "payment": CounterPaymentSerializer,
            "concession": ConcessionCreateSerializer,
            "cancel": CancelSerializer,
        }.get(self.action, InvoiceDetailSerializer)

    def body(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def detail_response(self, invoice, code=status.HTTP_200_OK):
        invoice = self.get_queryset().get(pk=invoice.pk)
        return Response(InvoiceDetailSerializer(invoice).data, status=code)

    @extend_schema(responses={201: PaymentSerializer})
    @action(detail=True, methods=["post"])
    def payment(self, request, pk=None):
        """Finance staff: record cash, UPI or a cheque taken at the office, up to the balance.
        Returns the payment with its receipt number; the receipt is emailed to the family."""
        invoice = self.get_object()
        data = self.body(request)
        payment = record_counter_payment(
            request.user, invoice, data["amount_paise"], data["method"], data["reference"]
        )
        return Response(PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses=InvoiceDetailSerializer)
    @action(detail=True, methods=["post"])
    def concession(self, request, pk=None):
        """Admins: reduce what is owed, with a reason (at most the balance). Audited."""
        invoice = self.get_object()
        data = self.body(request)
        return self.detail_response(
            grant_concession(request.user, invoice, data["amount_paise"], data["reason"])
        )

    @extend_schema(responses=InvoiceDetailSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Admins: cancel an invoice issued by mistake, only while nothing has been paid."""
        invoice = self.get_object()
        return self.detail_response(
            cancel_invoice(request.user, invoice, self.body(request)["reason"])
        )

    @extend_schema(
        request=None,
        responses={
            201: PaymentOrderSerializer,
            503: OpenApiResponse(description="The payment provider could not be reached"),
        },
    )
    @action(detail=True, methods=["post"], url_path="pay-online")
    def pay_online(self, request, pk=None):
        """A parent starts an online payment of the balance. Open `checkout_url` to pay; the
        payment is recorded when the provider confirms it (a signed webhook)."""
        try:
            order = start_online_payment(request.user, self.get_object())
        except GatewayError as exc:
            return Response(
                {"code": "gateway_unavailable", "detail": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(
            PaymentOrderSerializer(order, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class PaymentViewSet(viewsets.ReadOnlyModelViewSet):
    """Money received, newest first. `?excess=true`: payments with money held for refund."""

    queryset = Payment.objects.none()  # for the schema
    serializer_class = PaymentSerializer
    permission_classes = [FEES]
    filterset_class = PaymentFilter
    ordering_fields = ["paid_at", "amount_paise"]

    def get_queryset(self):
        return payments(self.request.user)


def collection_rows(request):
    """The validated ?start=&end=&branch= of a collection report, and its payments."""
    query = CollectionsQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    start, end = query.validated_data["start"], query.validated_data["end"]
    branch = selected_branch(request.user, request.query_params.get("branch"))
    return start, end, branch, collections(request.user, start, end, branch)


class CollectionsView(generics.GenericAPIView):
    """Money received between two dates: totals overall and per method (as on the web page)."""

    serializer_class = CollectionsSerializer
    permission_classes = [role_in(*User.FINANCE)]

    @extend_schema(summary="Fee collections", parameters=[CollectionsQuerySerializer])
    def get(self, request):
        start, end, _, rows = collection_rows(request)
        summary = collection_totals(rows)
        data = {
            "start": start,
            "end": end,
            "count": summary["count"],
            "received_paise": summary["received"],
            "applied_paise": summary["applied"],
            "excess_paise": summary["excess"],
            "by_method": [
                {"method": label, "received_paise": paise} for label, paise in summary["by_method"]
            ],
        }
        return Response(self.get_serializer(data).data)


class CollectionsExportView(generics.GenericAPIView):
    """The collection report as CSV, one row per payment: the same file as the web export.
    Audited."""

    permission_classes = [role_in(*User.FINANCE)]
    renderer_classes = [renderers.JSONRenderer, CSVRenderer]

    @extend_schema(
        summary="Download fee collections (CSV)",
        parameters=[CollectionsQuerySerializer],
        responses={(200, "text/csv"): OpenApiTypes.STR},
    )
    def get(self, request):
        start, end, branch, rows = collection_rows(request)
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="collections-{start:%Y%m%d}-{end:%Y%m%d}.csv"'
        )
        export_collections_csv(
            request.user, branch, start, end, rows.select_related("invoice__year"), response
        )
        return response


class PaymentOrderViewSet(viewsets.ReadOnlyModelViewSet):
    """Online checkouts. `?status=review`: captured payments that need a person to check."""

    queryset = PaymentOrder.objects.none()  # for the schema
    serializer_class = PaymentOrderSerializer
    permission_classes = [FEES]
    filterset_class = PaymentOrderFilter

    def get_queryset(self):
        return payment_orders(self.request.user)


class ReceiptPDFView(generics.GenericAPIView):
    """A payment's receipt as a PDF, the same file that was emailed."""

    renderer_classes = [renderers.JSONRenderer, PDFRenderer]
    permission_classes = [FEES]

    @extend_schema(responses={(200, "application/pdf"): OpenApiTypes.BINARY})
    def get(self, request, pk):
        receipt = get_object_or_404(receipts(request.user), pk=pk)
        response = HttpResponse(render_receipt(receipt.payment), content_type="application/pdf")
        response["Content-Disposition"] = (
            f'attachment; filename="{receipt_filename(receipt.payment)}"'
        )
        return response


class FeeSetupPermissions:
    """Finance staff read fee setup; admins (super and branch) create and change it. The services
    check the branch again."""

    def get_permissions(self):
        if self.action in ("create", "partial_update"):
            return [role_in(*User.MANAGERS)()]
        return [role_in(*User.FINANCE)()]


class FeeHeadViewSet(
    FeeSetupPermissions,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.ReadOnlyModelViewSet,
):
    """Kinds of charge (Tuition, Transport, ...) in the caller's branches."""

    queryset = FeeHead.objects.none()  # for the schema
    filterset_fields = ["branch"]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        return fee_heads(self.request.user)

    def get_serializer_class(self):
        return {"create": FeeHeadWriteSerializer, "partial_update": FeeHeadUpdateSerializer}.get(
            self.action, FeeHeadSerializer
        )

    @extend_schema(responses={201: FeeHeadSerializer})
    def create(self, request, *args, **kwargs):
        body = self.get_serializer(data=request.data)
        body.is_valid(raise_exception=True)
        head = save_fee_head(request.user, FeeHead(**body.validated_data))
        return Response(FeeHeadSerializer(head).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses=FeeHeadSerializer)
    def partial_update(self, request, *args, **kwargs):
        head = self.get_object()
        body = self.get_serializer(head, data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        for field, value in body.validated_data.items():
            setattr(head, field, value)
        return Response(FeeHeadSerializer(save_fee_head(request.user, head)).data)


class FeePlanViewSet(
    FeeSetupPermissions,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.ReadOnlyModelViewSet,
):
    """What each grade pays in a year. Admins create plans and change their amounts; `issue`
    invoices a grade (finance staff)."""

    queryset = FeePlan.objects.none()  # for the schema
    filterset_fields = ["branch", "year"]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_permissions(self):
        if self.action == "issue":
            return [role_in(*User.FINANCE)()]
        return super().get_permissions()

    def get_queryset(self):
        return fee_plans(self.request.user)

    def get_serializer_class(self):
        return {
            "issue": IssueInvoicesSerializer,
            "create": FeePlanWriteSerializer,
            "partial_update": FeePlanUpdateSerializer,
        }.get(self.action, FeePlanSerializer)

    def amounts(self, branch, items):
        """{FeeHead: paise} from the request's items; every head must be of the plan's branch."""
        heads = {head.pk: head for head in FeeHead.objects.filter(branch=branch)}
        unknown = [item["head"] for item in items if item["head"] not in heads]
        if unknown:
            raise ValidationError({"items": [f"Fee head {unknown[0]} isn't one of this branch's."]})
        return {heads[item["head"]]: item["amount_paise"] for item in items}

    def plan_response(self, plan, code=status.HTTP_200_OK):
        return Response(
            FeePlanSerializer(fee_plans(self.request.user).get(pk=plan.pk)).data, status=code
        )

    @extend_schema(responses={201: FeePlanSerializer})
    def create(self, request, *args, **kwargs):
        body = self.get_serializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        plan = FeePlan(branch=data["branch"], year=data["year"], grade=data["grade_id"])
        plan = save_fee_plan(request.user, plan, self.amounts(data["branch"], data["items"]))
        return self.plan_response(plan, status.HTTP_201_CREATED)

    @extend_schema(responses=FeePlanSerializer)
    def partial_update(self, request, *args, **kwargs):
        plan = self.get_object()
        body = self.get_serializer(data=request.data)
        body.is_valid(raise_exception=True)
        amounts = self.amounts(plan.branch, body.validated_data["items"])
        return self.plan_response(save_fee_plan(request.user, plan, amounts))

    @extend_schema(responses={201: IssueResultSerializer})
    @action(detail=True, methods=["post"])
    def issue(self, request, pk=None):
        """Invoice every student now in the plan's grade. Families are notified."""
        plan = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        created, skipped = issue_invoices(request.user, plan, **serializer.validated_data)
        result = {
            "created": len(created),
            "skipped": skipped,
            "invoices": [invoice.pk for invoice in created],
        }
        return Response(IssueResultSerializer(result).data, status=status.HTTP_201_CREATED)


class PaymentWebhookView(APIView):
    """Payment provider callback. Public, because the provider calls it, so nothing in it is
    trusted until the X-Razorpay-Signature header (HMAC SHA-256 of the raw body) checks out.

    Safe to deliver any number of times: a payment is recorded once.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer("WebhookResult", {"status": serializers.CharField()}),
            400: OpenApiResponse(description="Bad signature or not a payment event"),
        },
    )
    def post(self, request, gateway):
        if gateway not in GATEWAYS:
            raise Http404
        signature = request.headers.get("X-Razorpay-Signature", "")
        try:
            outcome = receive_webhook(gateway, request.body, signature)
        except InvalidSignature:
            return Response(
                {"code": "invalid_signature", "detail": "The signature does not match."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ValueError:
            return Response(
                {"code": "invalid", "detail": "Not a payment event."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"status": outcome})
