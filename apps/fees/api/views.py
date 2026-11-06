from django.http import Http404
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from ..gateways import GATEWAYS
from ..services import InvalidSignature, receive_webhook


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
