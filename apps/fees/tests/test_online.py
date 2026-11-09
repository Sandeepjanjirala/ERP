"""Online payments: signed webhooks, every check on the money, and no payment ever lost."""

import hashlib
import hmac
import io
import json
import os
import subprocess
import sys
from unittest import mock

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import override_settings

from apps.audit.models import AuditEvent
from apps.core.testing import ApiTestCase
from apps.fees.gateways import RazorpayGateway, SandboxGateway, parse_event
from apps.fees.models import Payment, PaymentOrder, Receipt
from apps.fees.selectors import excess_payments, orders_for_review
from apps.fees.services import (
    cancel_invoice,
    record_counter_payment,
    start_online_payment,
)
from apps.fees.tests.base import TOTAL, FeesTestCase

WEBHOOK = "/api/v1/payments/webhook/{}/"


class OnlineTestCase(ApiTestCase, FeesTestCase):
    def deliver(self, body, signature=None, gateway="sandbox"):
        signature = SandboxGateway().sign(body) if signature is None else signature
        return self.client.post(
            WEBHOOK.format(gateway),
            data=body,
            content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE=signature,
        )

    def capture(self, order, **changes):
        """A sandbox "payment captured" webhook body, optionally altered."""
        body = json.loads(SandboxGateway().event_body(order, "captured"))
        body["payload"]["payment"]["entity"].update(changes)
        return json.dumps(body).encode()


class HappyPathTests(OnlineTestCase):
    def test_start_capture_and_receipt(self):
        invoice = self.alices()
        order = start_online_payment(self.parent, invoice)
        self.assertEqual(
            (order.gateway, order.amount_paise, order.status), ("sandbox", TOTAL, "created")
        )

        response = self.deliver(self.capture(order))
        self.assertEqual(response.json(), {"status": "recorded"})
        invoice.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual((invoice.status, invoice.paid_paise), ("paid", TOTAL))
        self.assertEqual(order.status, "paid")
        payment = Payment.objects.get()
        self.assertEqual(
            (payment.method, payment.gateway, payment.order), ("online", "sandbox", order)
        )
        self.assertTrue(payment.gateway_payment_id.startswith("pay_SBX"))
        self.assertEqual(payment.receipt.sequence, 1)
        event = AuditEvent.objects.get(action="fees.online.captured")
        self.assertEqual(event.actor, self.parent)  # who started it; the webhook has no user
        self.assertEqual(event.details["receipt"], payment.receipt.number)

    def test_the_same_webhook_twice_records_one_payment(self):
        order = start_online_payment(self.parent, self.alices())
        body = self.capture(order)
        self.assertEqual(self.deliver(body).json(), {"status": "recorded"})
        self.assertEqual(self.deliver(body).json(), {"status": "duplicate"})
        self.assertEqual((Payment.objects.count(), Receipt.objects.count()), (1, 1))


class SignatureTests(OnlineTestCase):
    def test_unsigned_or_tampered_webhooks_change_nothing(self):
        order = start_online_payment(self.parent, self.alices())
        body = self.capture(order)
        tampered = body.replace(str(TOTAL).encode(), b"100")
        for case, (payload, signature) in {
            "wrong signature": (body, "0" * 64),
            "no signature": (body, ""),
            "amount changed after signing": (tampered, SandboxGateway().sign(body)),
        }.items():
            with self.subTest(case=case):
                response = self.deliver(payload, signature)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["code"], "invalid_signature")
        self.assertFalse(Payment.objects.exists())

    def test_unknown_providers_and_bodies(self):
        self.assertEqual(self.deliver(b"{}", gateway="paypal").status_code, 404)
        self.assertEqual(self.deliver(b"not json").json()["code"], "invalid")


class EventTests(OnlineTestCase):
    def test_orders_we_did_not_create_are_ignored(self):
        order = PaymentOrder(
            gateway_order_id="order_someone_else", amount_paise=100, currency="INR"
        )
        self.assertEqual(self.deliver(self.capture(order)).json(), {"status": "unknown_order"})

    def test_a_failed_attempt_then_a_successful_one(self):
        order = start_online_payment(self.parent, self.alices())
        failed = SandboxGateway().event_body(order, "failed")
        self.assertEqual(self.deliver(failed).json(), {"status": "failed"})
        order.refresh_from_db()
        self.assertEqual(order.status, "failed")
        self.assertEqual(self.deliver(self.capture(order)).json(), {"status": "recorded"})

    def test_events_that_are_not_captures_are_ignored(self):
        order = start_online_payment(self.parent, self.alices())
        authorised = self.capture(order, status="authorized")
        self.assertEqual(self.deliver(authorised).json(), {"status": "ignored"})
        self.assertFalse(Payment.objects.exists())


class MismatchTests(OnlineTestCase):
    def test_a_different_amount_is_recorded_and_flagged(self):
        order = start_online_payment(self.parent, self.alices())
        self.assertEqual(
            self.deliver(self.capture(order, amount=500000)).json(), {"status": "review"}
        )
        payment = Payment.objects.get()
        self.assertEqual((payment.amount_paise, payment.applied_paise), (500000, 500000))
        order.refresh_from_db()
        self.assertEqual(order.status, "review")
        self.assertIn("captured ₹5,000.00", order.problem)
        self.assertEqual(list(orders_for_review(self.accountant)), [order])

    def test_another_currency_is_kept_for_review_not_counted_as_rupees(self):
        invoice = self.alices()
        order = start_online_payment(self.parent, invoice)
        self.assertEqual(
            self.deliver(self.capture(order, currency="USD")).json(), {"status": "review"}
        )
        self.assertFalse(Payment.objects.exists())
        order.refresh_from_db()
        invoice.refresh_from_db()
        self.assertEqual(invoice.paid_paise, 0)
        self.assertEqual(
            (order.status, order.captured_currency, order.captured_amount_paise),
            ("review", "USD", TOTAL),
        )
        self.assertTrue(order.gateway_payment_id.startswith("pay_SBX"))
        self.assertTrue(AuditEvent.objects.filter(action="fees.online.review").exists())
        # And it stays recorded once: a repeat of the same webhook is a duplicate.
        body = self.capture(order, currency="USD", id=order.gateway_payment_id)
        self.assertEqual(self.deliver(body).json(), {"status": "duplicate"})


class ExcessTests(OnlineTestCase):
    def test_money_that_crosses_a_counter_payment_is_kept_as_excess(self):
        invoice = self.alices()
        order = start_online_payment(self.parent, invoice)  # the parent opens the checkout...
        record_counter_payment(self.accountant, invoice, TOTAL, "cash")  # ...the office takes cash
        self.assertEqual(self.deliver(self.capture(order)).json(), {"status": "recorded"})
        invoice.refresh_from_db()
        self.assertEqual(invoice.paid_paise, TOTAL)  # never overpaid
        online = Payment.objects.get(method="online")
        self.assertEqual((online.applied_paise, online.excess_paise), (0, TOTAL))
        self.assertTrue(online.receipt.number)  # real money gets a receipt
        self.assertEqual(list(excess_payments(self.accountant)), [online])

    def test_a_second_capture_for_a_paid_order(self):
        order = start_online_payment(self.parent, self.alices())
        self.deliver(self.capture(order))
        self.assertEqual(self.deliver(self.capture(order)).json(), {"status": "review"})
        second = Payment.objects.order_by("pk").last()
        self.assertEqual((second.order, second.excess_paise), (None, TOTAL))
        order.refresh_from_db()
        self.assertIn("already paid", order.problem)

    def test_money_for_a_cancelled_invoice_is_kept(self):
        invoice = self.alices()
        order = start_online_payment(self.parent, invoice)
        cancel_invoice(self.admin, invoice, "Issued by mistake")
        self.deliver(self.capture(order))
        invoice.refresh_from_db()
        self.assertEqual((invoice.status, invoice.paid_paise), ("cancelled", 0))
        self.assertEqual(Payment.objects.get().excess_paise, TOTAL)


class StartRulesTests(OnlineTestCase):
    def test_only_the_childs_parent_pays_online_and_only_what_is_owed(self):
        issued = self.issue()
        alice, bob = issued[self.e1.student_id], issued[self.e2.student_id]
        for actor, invoice in ((self.parent, bob), (self.accountant, alice), (self.teacher, alice)):
            with self.subTest(actor=actor.username), self.assertRaises(PermissionDenied):
                start_online_payment(actor, invoice)
        record_counter_payment(self.accountant, alice, TOTAL, "cash")
        with self.assertRaises(ValidationError):
            start_online_payment(self.parent, alice)


class RazorpayTests(OnlineTestCase):
    @override_settings(RAZORPAY_WEBHOOK_SECRET="whsec_test_123")
    def test_webhooks_signed_with_the_razorpay_secret(self):
        order = PaymentOrder.objects.create(
            invoice=self.alices(),
            gateway="razorpay",
            gateway_order_id="order_RZP1",
            amount_paise=TOTAL,
            created_by=self.parent,
        )
        body = self.capture(order)
        good = hmac.new(b"whsec_test_123", body, hashlib.sha256).hexdigest()
        self.assertEqual(self.deliver(body, "f" * 64, "razorpay").status_code, 400)
        self.assertEqual(self.deliver(body, good, "razorpay").json(), {"status": "recorded"})

    def test_without_a_webhook_secret_nothing_verifies(self):
        self.assertFalse(RazorpayGateway().verify(b"{}", ""))

    @override_settings(RAZORPAY_KEY_ID="rzp_test_abc", RAZORPAY_KEY_SECRET="secret_xyz")
    def test_checkout_signature_and_order_creation(self):
        gateway = RazorpayGateway()
        expected = hmac.new(b"secret_xyz", b"order_1|pay_1", hashlib.sha256).hexdigest()
        self.assertTrue(gateway.verify_checkout("order_1", "pay_1", expected))
        self.assertFalse(gateway.verify_checkout("order_1", "pay_2", expected))
        reply = io.BytesIO(json.dumps({"id": "order_RZP9"}).encode())
        reply.__enter__ = lambda self=reply: self
        reply.__exit__ = lambda *args: False
        with mock.patch("urllib.request.urlopen", return_value=reply) as urlopen:
            self.assertEqual(gateway.create_order(TOTAL, "INR", "invoice-1"), "order_RZP9")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.razorpay.com/v1/orders")
        self.assertEqual(
            json.loads(request.data), {"amount": TOTAL, "currency": "INR", "receipt": "invoice-1"}
        )

    def test_parse_event_rejects_other_shapes(self):
        for body in (b"{}", b'{"event": "payment.captured"}', b"[]"):
            with self.subTest(body=body), self.assertRaises(ValueError):
                parse_event(body)


class TestModeOnlyTests(OnlineTestCase):
    def test_live_razorpay_keys_are_refused(self):
        """EduNexa must never take real money: a rzp_live_ key stops it from starting."""
        env = {
            **os.environ,
            "RAZORPAY_KEY_ID": "rzp_live_abc",
            "DJANGO_SETTINGS_MODULE": "config.settings.test",
            "DJANGO_ENV_FILE": "no-such-file.env",
        }
        result = subprocess.run(
            [sys.executable, "-c", "import django; django.setup()"],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("test mode only", result.stderr)
