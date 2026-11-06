from django.db.models import Prefetch
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import generics, renderers, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.core.api.permissions import role_in
from apps.core.api.renderers import PDFRenderer

from ..gateways import GATEWAYS, GatewayError
from ..models import FeeHead, FeePlan, Invoice, Payment, PaymentOrder
from ..pdf import receipt_filename, render_receipt
from ..selectors import fee_heads, fee_plans, invoices, payment_orders, payments, receipts
from ..services import (
    InvalidSignature,
    cancel_invoice,
    grant_concession,
    issue_invoices,
    receive_webhook,
    record_counter_payment,
    start_online_payment,
)
from .filters import InvoiceFilter, PaymentFilter, PaymentOrderFilter
from .serializers import (
    CancelSerializer,
    ConcessionCreateSerializer,
    CounterPaymentSerializer,
    FeeHeadSerializer,
    FeePlanSerializer,
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


class FeeHeadViewSet(viewsets.ReadOnlyModelViewSet):
    """Kinds of charge (Tuition, Transport, ...) in the caller's branches."""

    queryset = FeeHead.objects.none()  # for the schema
    serializer_class = FeeHeadSerializer
    permission_classes = [role_in(*User.FINANCE)]
    filterset_fields = ["branch"]

    def get_queryset(self):
        return fee_heads(self.request.user)


class FeePlanViewSet(viewsets.ReadOnlyModelViewSet):
    """What each grade pays in a year. Plans are set up on the web; `issue` invoices a grade."""

    queryset = FeePlan.objects.none()  # for the schema
    permission_classes = [role_in(*User.FINANCE)]
    filterset_fields = ["branch", "year"]

    def get_queryset(self):
        return fee_plans(self.request.user)

    def get_serializer_class(self):
        return IssueInvoicesSerializer if self.action == "issue" else FeePlanSerializer

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
