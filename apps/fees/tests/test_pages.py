"""The fees web pages: who sees and does what, and the whole online payment from the browser."""

import hashlib
import hmac
from datetime import timedelta
from unittest import mock

from django.test import override_settings
from django.urls import reverse

from apps.academics.models import Grade
from apps.core.testing import pdf_text
from apps.fees.models import FeeHead, FeePlan, Invoice, Payment, PaymentOrder
from apps.fees.services import (
    record_counter_payment,
    simulate_sandbox_payment,
    start_online_payment,
)
from apps.fees.tests.base import TOTAL, TUITION, FeesTestCase


class InvoiceDetailPageTests(FeesTestCase):
    def test_what_each_role_can_do_on_an_invoice(self):
        invoice = self.alices()
        url = reverse("invoice_detail", args=[invoice.pk])
        expectations = {
            # user: (record a payment, concession, cancel, pay online)
            self.accountant: (True, False, False, False),
            self.admin: (True, True, True, False),
            self.parent: (False, False, False, True),
        }
        for user, flags in expectations.items():
            with self.subTest(user=user.username):
                self.client.force_login(user)
                context = self.client.get(url).context
                self.assertEqual(
                    tuple(
                        context[k] for k in ("can_collect", "can_concede", "can_cancel", "can_pay")
                    ),
                    flags,
                )
        self.client.force_login(self.parent)
        self.assertNotContains(self.client.get(url), "Online checkouts")  # staff only
        bobs = Invoice.objects.get(student=self.e2.student)
        self.assertEqual(
            self.client.get(reverse("invoice_detail", args=[bobs.pk])).status_code, 404
        )
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_recording_a_payment_at_the_office(self):
        invoice = self.alices()
        url = reverse("payment_record", args=[invoice.pk])
        self.client.force_login(self.accountant)
        page = self.client.post(url, {"amount": "5,000.50", "method": "upi", "reference": ""})
        self.assertFormError(
            page.context["payment_form"], "reference", "Enter the UPI or cheque reference."
        )
        page = self.client.post(url, {"amount": "99,999", "method": "cash"})
        self.assertFormError(
            page.context["payment_form"], "amount", "Enter an amount up to the balance, ₹12,500.00."
        )
        page = self.client.post(url, {"amount": "₹5,000.50", "method": "cash"}, follow=True)
        payment = Payment.objects.get()
        self.assertEqual(payment.amount_paise, 500050)
        self.assertContains(page, f"Receipt {payment.receipt.number}")
        self.client.force_login(self.parent)
        self.assertEqual(self.client.post(url, {"amount": "1", "method": "cash"}).status_code, 403)

    def test_concessions_and_cancelling(self):
        issued = self.issue()
        alice, bob = issued[self.e1.student_id], issued[self.e2.student_id]
        self.client.force_login(self.accountant)
        concession = reverse("concession_grant", args=[alice.pk])
        self.assertEqual(
            self.client.post(concession, {"amount": "1", "reason": "x"}).status_code, 403
        )
        self.client.force_login(self.admin)
        self.client.post(concession, {"amount": "500.50", "reason": "Sibling discount"})
        alice.refresh_from_db()
        self.assertEqual(alice.total_paise, TOTAL - 50050)

        cancel = reverse("invoice_cancel", args=[bob.pk])
        page = self.client.post(cancel, {"reason": ""})
        self.assertFormError(page.context["cancel_form"], "reason", "This field is required.")
        self.client.post(cancel, {"reason": "Left the school"})
        bob.refresh_from_db()
        self.assertEqual((bob.status, bob.cancel_reason), ("cancelled", "Left the school"))

    def test_receipt_pdf(self):
        invoice = self.alices()
        receipt = record_counter_payment(self.accountant, invoice, TUITION, "cash").receipt
        url = reverse("receipt_pdf", args=[receipt.pk])
        for user in (self.parent, self.accountant):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                response = self.client.get(url)
                self.assertEqual(response["Content-Type"], "application/pdf")
                self.assertIn(receipt.number, pdf_text(response.content))
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(url).status_code, 403)
        bobs = Invoice.objects.get(student=self.e2.student)
        other = record_counter_payment(self.accountant, bobs, TUITION, "cash").receipt
        self.client.force_login(self.parent)
        self.assertEqual(self.client.get(reverse("receipt_pdf", args=[other.pk])).status_code, 404)


class SandboxCheckoutTests(FeesTestCase):
    def test_a_parent_pays_online_from_the_invoice_page(self):
        invoice = self.alices()
        self.client.force_login(self.parent)
        response = self.client.post(reverse("pay_online", args=[invoice.pk]))
        order = PaymentOrder.objects.get()
        self.assertRedirects(response, reverse("checkout", args=[order.pk]))
        page = self.client.get(response.url)
        self.assertContains(page, "Test payment: no money moves.")

        failed = self.client.post(
            reverse("sandbox_pay", args=[order.pk]), {"outcome": "failed"}, follow=True
        )
        self.assertContains(failed, "The payment did not go through.")
        self.assertEqual(self.client.get(response.url).status_code, 200)  # can try again

        paid = self.client.post(
            reverse("sandbox_pay", args=[order.pk]), {"outcome": "captured"}, follow=True
        )
        self.assertContains(paid, "Payment received.")
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "paid")
        self.assertEqual(self.client.get(response.url).status_code, 404)  # the order is done
        # Nothing left to pay: no button, and starting again is refused with a message.
        self.assertFalse(paid.context["can_pay"])
        again = self.client.post(reverse("pay_online", args=[invoice.pk]), follow=True)
        self.assertContains(again, "This invoice has nothing left to pay.")

    def test_only_the_parent_reaches_the_checkout(self):
        order = start_online_payment(self.parent, self.alices())
        for user in (self.accountant, self.admin, self.teacher):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.assertEqual(
                    self.client.get(reverse("checkout", args=[order.pk])).status_code, 403
                )
                self.assertEqual(
                    self.client.post(
                        reverse("sandbox_pay", args=[order.pk]), {"outcome": "captured"}
                    ).status_code,
                    403,
                )
        self.assertFalse(Payment.objects.exists())


@override_settings(
    RAZORPAY_KEY_ID="rzp_test_abc", RAZORPAY_KEY_SECRET="secret_xyz", PAYMENT_GATEWAY="razorpay"
)
class RazorpayCheckoutTests(FeesTestCase):
    def setUp(self):
        self.invoice = self.alices()
        with mock.patch(
            "apps.fees.gateways.RazorpayGateway.create_order", return_value="order_RZP1"
        ):
            self.order = start_online_payment(self.parent, self.invoice)
        self.client.force_login(self.parent)

    def callback(self, payment_id="pay_RZP1", signature=None, fetched=None):
        if signature is None:
            message = f"order_RZP1|{payment_id}".encode()
            signature = hmac.new(b"secret_xyz", message, hashlib.sha256).hexdigest()
        reply = {
            "id": payment_id,
            "order_id": "order_RZP1",
            "amount": TOTAL,
            "currency": "INR",
            "status": "captured",
            **(fetched or {}),
        }
        with mock.patch(
            "apps.fees.gateways.RazorpayGateway.fetch_payment", return_value=reply
        ) as fetch:
            page = self.client.post(
                reverse("razorpay_callback", args=[self.order.pk]),
                {"razorpay_payment_id": payment_id, "razorpay_signature": signature},
                follow=True,
            )
        return page, fetch

    def test_the_checkout_page_allows_razorpay_and_keeps_secrets_out(self):
        page = self.client.get(reverse("checkout", args=[self.order.pk]))
        self.assertEqual(self.order.gateway, "razorpay")
        policy = dict(part.split(" ", 1) for part in page["Content-Security-Policy"].split("; "))
        self.assertIn("https://checkout.razorpay.com", policy["script-src"])
        self.assertIn("https://api.razorpay.com", policy["frame-src"])
        self.assertContains(page, '"order_id": "order_RZP1"')
        self.assertContains(page, "rzp_test_abc")  # the public key id is meant for the browser
        self.assertNotContains(page, "secret_xyz")
        # Every other page keeps the strict policy.
        other = self.client.get(reverse("fees"))["Content-Security-Policy"]
        self.assertNotIn("razorpay", other)

    def test_a_verified_capture_is_recorded_once(self):
        page, fetch = self.callback()
        fetch.assert_called_once_with("pay_RZP1")
        self.assertContains(page, "Payment received.")
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "paid")
        # The webhook for the same payment arriving afterwards changes nothing.
        page, _ = self.callback()
        self.assertEqual((Payment.objects.count(), self.invoice.payments.count()), (1, 1))

    def test_nothing_from_the_browser_is_trusted(self):
        page, fetch = self.callback(signature="0" * 64)
        self.assertContains(page, "could not be verified")
        fetch.assert_not_called()
        # A real signature, but Razorpay says the payment belongs to another order.
        page, _ = self.callback(fetched={"order_id": "order_OTHER"})
        self.assertContains(page, "could not be verified")
        self.assertFalse(Payment.objects.exists())

    def test_amount_comes_from_razorpay_not_the_browser(self):
        self.callback(fetched={"amount": 100000})
        self.assertEqual(Payment.objects.get().amount_paise, 100000)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "review")

    def test_a_payment_not_yet_captured_waits_for_the_webhook(self):
        page, _ = self.callback(fetched={"status": "authorized"})
        self.assertContains(page, "being confirmed")
        self.assertFalse(Payment.objects.exists())


class FeeSetupPageTests(FeesTestCase):
    def test_admins_set_up_fees_and_accountants_issue(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse("fee_head_create", args=[self.a.pk]), {"name": "Library", "code": "library"}
        )
        library = FeeHead.objects.get(code="library")
        page = self.client.post(
            reverse("fee_head_create", args=[self.a.pk]), {"name": "Again", "code": "library"}
        )
        self.assertContains(page, "Fee head with this Branch and Code already exists.")

        self.client.post(
            reverse("fee_plan_edit", args=[self.plan.pk]),
            {f"head_{self.tuition.pk}": "11,000", f"head_{library.pk}": "500"},
        )
        amounts = {item.head.code: item.amount_paise for item in self.plan.items.all()}
        self.assertEqual(amounts, {"tuition": 1100000, "library": 50000})  # transport removed

        self.client.force_login(self.accountant)
        page = self.client.get(reverse("fee_setup"))
        self.assertNotContains(page, f'href="{reverse("fee_plan_edit", args=[self.plan.pk])}"')
        self.assertContains(page, f'href="{reverse("invoices_issue", args=[self.plan.pk])}"')
        self.assertEqual(
            self.client.get(reverse("fee_head_create", args=[self.a.pk])).status_code, 403
        )
        issue = reverse("invoices_issue", args=[self.plan.pk])
        yesterday = (self.today - timedelta(days=1)).isoformat()
        page = self.client.post(issue, {"title": "Term 2", "due_on": yesterday})
        self.assertFormError(
            page.context["form"], "due_on", "The due date can't be before today, the issue date."
        )
        due = (self.today + timedelta(days=30)).isoformat()
        page = self.client.post(issue, {"title": "Term 2", "due_on": due}, follow=True)
        self.assertContains(page, "2 invoices issued.")
        page = self.client.post(issue, {"title": "Term 2", "due_on": due}, follow=True)
        self.assertContains(page, "2 students already had this invoice")
        self.assertEqual(Invoice.objects.get(student=self.e1.student).total_paise, 1150000)

    def test_a_new_plan_for_a_grade_with_no_classroom_is_refused(self):
        self.client.force_login(self.admin)
        empty = Grade.objects.create(branch=self.a, name="Class 42", order=42)
        url = reverse("fee_plan_create", args=[self.a.pk])
        page = self.client.get(url)
        # Only this branch's grades are offered (South's grade 9 is not).
        offered = list(page.context["form"].fields["grade"].queryset)
        self.assertEqual(offered, [self.grade9, empty])
        page = self.client.post(
            url, {"year": self.year.pk, "grade": empty.pk, f"head_{self.tuition.pk}": "1"}
        )
        self.assertContains(page, "No classroom in this branch and year has that grade.")
        page = self.client.post(
            url, {"year": self.year.pk, "grade": self.grade9.pk, f"head_{self.tuition.pk}": "1"}
        )
        self.assertContains(page, "Fee plan with this Branch, Year and Grade already exists.")
        page = self.client.post(
            url,
            {"year": self.year.pk, "grade": self.foreign_grade9.pk, f"head_{self.tuition.pk}": "1"},
        )
        self.assertContains(page, "Select a valid choice.")
        self.assertEqual(FeePlan.objects.count(), 1)

    def test_other_branches_are_out_of_reach(self):
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.get(reverse("fee_head_create", args=[self.b.pk])).status_code, 404
        )
        sections = self.client.get(reverse("fee_setup")).context["sections"]
        self.assertEqual([s["branch"] for s in sections], [self.a])


class ReviewPageTests(FeesTestCase):
    def test_excess_money_is_listed_for_finance_only(self):
        invoice = self.alices()
        order = start_online_payment(self.parent, invoice)
        record_counter_payment(self.accountant, invoice, TOTAL, "cash")
        simulate_sandbox_payment(self.parent, order, "captured")
        self.client.force_login(self.accountant)
        page = self.client.get(reverse("payment_review"))
        self.assertEqual(len(page.context["excess"]), 1)
        self.assertContains(page, "₹12,500.00")
        self.client.force_login(self.parent)
        self.assertEqual(self.client.get(reverse("payment_review")).status_code, 403)

    def test_sidebar_links(self):
        for user, shown in ((self.accountant, True), (self.parent, True), (self.teacher, False)):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                page = self.client.get(reverse("announcements"))
                self.assertEqual(f'href="{reverse("fees")}"' in page.content.decode(), shown)
