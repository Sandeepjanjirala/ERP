"""Payment providers behind one interface.

The built-in Sandbox sends events in Razorpay's own format and signs them the same way (HMAC
SHA-256 of the raw body), so both providers go through exactly the same checks.
"""

import base64
import hashlib
import hmac
import json
import secrets
import urllib.error
import urllib.request
from dataclasses import dataclass

from django.conf import settings
from django.utils.crypto import salted_hmac


class GatewayError(Exception):
    """The provider could not be reached or refused the request."""


@dataclass(frozen=True)
class PaymentEvent:
    """What a provider says happened to a payment."""

    kind: str  # "captured", "failed" or "other"
    order_id: str
    payment_id: str
    amount_paise: int
    currency: str
    status: str


def payment_event(entity, kind):
    """A Razorpay payment entity (from a webhook or the payments API) as a PaymentEvent."""
    try:
        return PaymentEvent(
            kind=kind,
            order_id=str(entity["order_id"]),
            payment_id=str(entity["id"]),
            amount_paise=int(entity["amount"]),
            currency=str(entity["currency"]),
            status=str(entity["status"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Not a payment.") from error


def parse_event(body):
    """A Razorpay-format webhook body as a PaymentEvent. ValueError if it isn't one."""
    try:
        data = json.loads(body)
        entity = data["payload"]["payment"]["entity"]
        kind = {"payment.captured": "captured", "payment.failed": "failed"}.get(
            data["event"], "other"
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Not a payment event.") from error
    return payment_event(entity, kind)


class Gateway:
    name = ""

    def secret(self):
        raise NotImplementedError

    def sign(self, body):
        return hmac.new(self.secret().encode(), body, hashlib.sha256).hexdigest()

    def verify(self, body, signature):
        """Constant-time comparison, so the check leaks nothing about the right signature."""
        return bool(self.secret()) and hmac.compare_digest(self.sign(body), signature or "")

    def create_order(self, amount_paise, currency, receipt):
        raise NotImplementedError


class SandboxGateway(Gateway):
    """Test payments inside EduNexa: no keys, no network, no money."""

    name = "sandbox"

    def secret(self):
        return salted_hmac("edunexa.fees.sandbox-webhook", "v1").hexdigest()

    def create_order(self, amount_paise, currency, receipt):
        return f"order_SBX{secrets.token_hex(8)}"

    def event_body(self, order, outcome):
        """The webhook body Razorpay would send for this order, as bytes."""
        event = "payment.captured" if outcome == "captured" else "payment.failed"
        payload = {
            "event": event,
            "payload": {
                "payment": {
                    "entity": {
                        "id": f"pay_SBX{secrets.token_hex(8)}",
                        "order_id": order.gateway_order_id,
                        "amount": order.amount_paise,
                        "currency": order.currency,
                        "status": "captured" if outcome == "captured" else "failed",
                    }
                }
            },
        }
        return json.dumps(payload).encode()


class RazorpayGateway(Gateway):
    """Razorpay in test mode (keys starting rzp_test_; settings refuse any other)."""

    name = "razorpay"
    api = "https://api.razorpay.com/v1"

    def secret(self):
        return settings.RAZORPAY_WEBHOOK_SECRET

    def _request(self, method, path, payload=None):
        credentials = f"{settings.RAZORPAY_KEY_ID}:{settings.RAZORPAY_KEY_SECRET}"
        request = urllib.request.Request(
            f"{self.api}{path}",
            data=json.dumps(payload).encode() if payload is not None else None,
            method=method,
            headers={
                "Authorization": "Basic " + base64.b64encode(credentials.encode()).decode(),
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.load(response)
        except (urllib.error.URLError, ValueError) as error:
            raise GatewayError("Razorpay could not be reached. Please try again.") from error

    def create_order(self, amount_paise, currency, receipt):
        order = self._request(
            "POST", "/orders", {"amount": amount_paise, "currency": currency, "receipt": receipt}
        )
        return order["id"]

    def fetch_payment(self, payment_id):
        return self._request("GET", f"/payments/{payment_id}")

    def verify_checkout(self, order_id, payment_id, signature):
        """The signature Razorpay's checkout hands the browser: HMAC of "order|payment"."""
        expected = hmac.new(
            settings.RAZORPAY_KEY_SECRET.encode(),
            f"{order_id}|{payment_id}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return bool(settings.RAZORPAY_KEY_SECRET) and hmac.compare_digest(expected, signature or "")


GATEWAYS = {gateway.name: gateway for gateway in (SandboxGateway, RazorpayGateway)}


def get_gateway(name=None):
    """The configured provider (Razorpay with test keys, otherwise the Sandbox), or one by name."""
    return GATEWAYS[name or settings.PAYMENT_GATEWAY]()
