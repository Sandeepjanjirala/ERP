"""The fees API: the same services as the web pages, scoped the same way. (Which role may call
which endpoint: apps/core/tests/test_api_permissions.py.)"""

from datetime import timedelta

from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.academics.models import Classroom, Grade
from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.core.testing import PASSWORD, ApiTestCase, pdf_text
from apps.fees.gateways import SandboxGateway
from apps.fees.models import FeeHead, Invoice, PaymentOrder
from apps.fees.services import record_counter_payment
from apps.fees.tests.base import TOTAL, TUITION, FeesTestCase
from apps.students.tests.factories import EnrollmentFactory


class FeesApiTestCase(ApiTestCase, FeesTestCase):
    pass


class InvoiceApiTests(FeesApiTestCase):
    def test_each_caller_sees_only_their_invoices(self):
        issued = self.issue()
        alice, bob = issued[self.e1.student_id], issued[self.e2.student_id]
        self.as_user(self.parent)
        rows = self.client.get("/api/v1/invoices/").json()["results"]
        self.assertEqual([row["id"] for row in rows], [alice.pk])
        self.assertEqual(rows[0]["balance_paise"], TOTAL)
        self.assertEqual(self.client.get(f"/api/v1/invoices/{bob.pk}/").status_code, 404)
        # Another branch's accountant sees none of North's invoices.
        south = User.objects.create_user(
            "southaccounts",
            "sa@example.com",
            PASSWORD,
            role="accountant",
            branch=self.b,
            must_change_password=False,
        )
        self.as_user(south)
        self.assertEqual(self.client.get("/api/v1/invoices/").json()["count"], 0)
        self.assertEqual(self.client.get(f"/api/v1/invoices/{alice.pk}/").status_code, 404)

    def test_filters(self):
        issued = self.issue(due_in=0)
        overdue = self.issue(title="Old term", due_in=0)[self.e2.student_id]
        Invoice.objects.filter(pk=overdue.pk).update(
            issued_on=self.today - timedelta(days=9), due_on=self.today - timedelta(days=1)
        )
        record_counter_payment(self.accountant, issued[self.e1.student_id], TOTAL, "cash")
        self.as_user(self.accountant)

        def ids(query):
            return [
                row["id"] for row in self.client.get(f"/api/v1/invoices/?{query}").json()["results"]
            ]

        self.assertEqual(ids("overdue=true"), [overdue.pk])
        self.assertEqual(ids("status=paid"), [issued[self.e1.student_id].pk])
        self.assertEqual(sorted(ids("q=bob")), sorted([overdue.pk, issued[self.e2.student_id].pk]))
        self.assertEqual(ids(f"student={self.foreign_enrollment.student_id}"), [])

    def test_detail_has_lines_concessions_and_payments(self):
        invoice = self.alices()
        record_counter_payment(self.accountant, invoice, TUITION, "cash")
        self.as_user(self.parent)
        body = self.client.get(f"/api/v1/invoices/{invoice.pk}/").json()
        self.assertEqual([line["amount_paise"] for line in body["lines"]], [250000, TUITION])
        self.assertEqual(body["payments"][0]["receipt_number"][-5:], "00001")
        self.assertEqual(body["status"], "partly_paid")


class InvoiceActionApiTests(FeesApiTestCase):
    def test_recording_a_payment(self):
        invoice = self.alices()
        url = f"/api/v1/invoices/{invoice.pk}/payment/"
        self.as_user(self.accountant)
        response = self.client.post(url, {"amount_paise": TOTAL + 1, "method": "cash"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("amount_paise", response.json()["fields"])
        response = self.client.post(url, {"amount_paise": 500, "method": "cheque"})
        self.assertEqual(
            response.json()["fields"], {"reference": ["Enter the UPI or cheque reference."]}
        )
        response = self.client.post(url, {"amount_paise": 500, "method": "online"})
        self.assertEqual(response.status_code, 400)  # online money only comes from a provider
        response = self.client.post(
            url, {"amount_paise": TOTAL, "method": "upi", "reference": "UPI-123"}
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            (response.json()["applied_paise"], response.json()["excess_paise"]), (TOTAL, 0)
        )
        receipt = response.json()["receipt_id"]
        pdf = self.client.get(f"/api/v1/receipts/{receipt}/pdf/", HTTP_ACCEPT="application/pdf")
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertIn("UPI-123", pdf_text(pdf.content))
        self.assertEqual(
            self.client.post(url, {"amount_paise": 1, "method": "cash"}).status_code, 400
        )

    def test_concession_and_cancel(self):
        issued = self.issue()
        alice, bob = issued[self.e1.student_id], issued[self.e2.student_id]
        self.as_user(self.admin)
        response = self.client.post(
            f"/api/v1/invoices/{alice.pk}/concession/", {"amount_paise": 100, "reason": "Merit"}
        )
        self.assertEqual(response.json()["total_paise"], TOTAL - 100)
        self.assertEqual(response.json()["concessions"][0]["reason"], "Merit")
        response = self.client.post(f"/api/v1/invoices/{bob.pk}/cancel/", {"reason": "Duplicate"})
        self.assertEqual(
            (response.json()["status"], response.json()["balance_paise"]), ("cancelled", 0)
        )
        response = self.client.post(f"/api/v1/invoices/{bob.pk}/cancel/", {"reason": "Again"})
        self.assertEqual(response.status_code, 400)

    def test_paying_online_through_the_api(self):
        invoice = self.alices()
        self.as_user(self.parent)
        response = self.client.post(f"/api/v1/invoices/{invoice.pk}/pay-online/")
        self.assertEqual(response.status_code, 201)
        order = PaymentOrder.objects.get(pk=response.json()["id"])
        self.assertTrue(response.json()["checkout_url"].endswith(f"/fees/checkout/{order.pk}/"))
        self.assertEqual(response.json()["amount_paise"], TOTAL)
        # The provider confirms it with a signed webhook.
        gateway = SandboxGateway()
        body = gateway.event_body(order, "captured")
        self.client.force_authenticate(None)
        self.client.post(
            "/api/v1/payments/webhook/sandbox/",
            data=body,
            content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE=gateway.sign(body),
        )
        self.as_user(self.parent)
        orders = self.client.get("/api/v1/payment-orders/").json()["results"]
        self.assertEqual([o["status"] for o in orders], ["paid"])
        payments = self.client.get("/api/v1/payments/").json()["results"]
        self.assertEqual([(p["method"], p["amount_paise"]) for p in payments], [("online", TOTAL)])
        again = self.client.post(f"/api/v1/invoices/{invoice.pk}/pay-online/")
        self.assertEqual(again.json()["detail"], "This invoice has nothing left to pay.")

    def test_issuing_invoices(self):
        self.as_user(self.accountant)
        url = f"/api/v1/fee-plans/{self.plan.pk}/issue/"
        past = {"title": "Term 1", "due_on": (self.today - timedelta(days=1)).isoformat()}
        self.assertEqual(self.client.post(url, past).status_code, 400)
        body = {"title": "Term 1", "due_on": (self.today + timedelta(days=10)).isoformat()}
        first = self.client.post(url, body).json()
        self.assertEqual((first["created"], first["skipped"], len(first["invoices"])), (2, 0, 2))
        again = self.client.post(url, body).json()
        self.assertEqual((again["created"], again["skipped"]), (0, 2))
        plans = self.client.get("/api/v1/fee-plans/").json()["results"]
        self.assertEqual(plans[0]["total_paise"], TOTAL)

    def test_excess_payments_filter(self):
        invoice = self.alices()
        self.as_user(self.accountant)
        record_counter_payment(self.accountant, invoice, TUITION, "cash")
        self.assertEqual(self.client.get("/api/v1/payments/?excess=true").json()["count"], 0)
        self.assertEqual(self.client.get("/api/v1/payments/?excess=false").json()["count"], 1)


class FeesQueryCountTests(FeesApiTestCase):
    """Fee lists cost the same number of queries for 2 students as for 12."""

    def queries(self, url):
        with CaptureQueriesContext(connection) as context:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.content)
        return len(context)

    def grow(self, n, title):
        EnrollmentFactory.create_batch(n, classroom=self.c)
        created = self.issue(title=title)
        for invoice in created.values():
            record_counter_payment(self.accountant, invoice, 100, "cash")

    def test_lists_and_detail_have_no_n_plus_one(self):
        self.as_user(self.accountant)
        self.grow(0, "Term 1")
        urls = ["/api/v1/invoices/?page_size=100", "/api/v1/payments/?page_size=100"]
        few = [self.queries(url) for url in urls]
        invoice = Invoice.objects.filter(student=self.e1.student).first()
        detail = self.queries(f"/api/v1/invoices/{invoice.pk}/")
        self.grow(10, "Term 2")
        for _ in range(5):
            record_counter_payment(self.accountant, invoice, 100, "cash")
        self.assertEqual([self.queries(url) for url in urls], few)
        self.assertEqual(self.queries(f"/api/v1/invoices/{invoice.pk}/"), detail)


class FeeSetupApiTests(FeesApiTestCase):
    """Fee heads and plans through the API: the same services and rules as the web pages."""

    def test_admins_create_and_change_heads_and_plans(self):
        self.as_user(self.admin)
        head = self.client.post(
            "/api/v1/fee-heads/", {"branch": self.a.pk, "name": "Library", "code": "library"}
        )
        self.assertEqual(head.status_code, 201, head.content)
        again = self.client.post(
            "/api/v1/fee-heads/", {"branch": self.a.pk, "name": "Again", "code": "library"}
        )
        self.assertEqual(again.status_code, 400)
        renamed = self.client.patch(
            f"/api/v1/fee-heads/{head.json()['id']}/", {"name": "Library fee"}
        )
        self.assertEqual(renamed.json()["name"], "Library fee")
        self.assertEqual(
            self.client.post(
                "/api/v1/fee-heads/", {"branch": self.b.pk, "name": "X", "code": "x"}
            ).status_code,
            400,
        )  # another branch is out of scope

        grade10 = Grade.objects.create(branch=self.a, name="10", order=10)
        Classroom.objects.create(branch=self.a, year=self.year, grade=grade10, section="A")
        body = {
            "branch": self.a.pk,
            "year": self.year.pk,
            "grade_id": grade10.pk,
            "items": [{"head": self.tuition.pk, "amount_paise": 1500000}, {"head": head.json()["id"], "amount_paise": 50000}],
        }  # fmt: skip
        plan = self.client.post("/api/v1/fee-plans/", body, format="json")
        self.assertEqual(plan.status_code, 201, plan.content)
        self.assertEqual((plan.json()["grade"], plan.json()["total_paise"]), ("10", 1550000))
        foreign = FeeHead.objects.create(branch=self.b, name="Bus", code="bus")
        bad = self.client.patch(
            f"/api/v1/fee-plans/{plan.json()['id']}/",
            {"items": [{"head": foreign.pk, "amount_paise": 100}]},
            format="json",
        )
        self.assertEqual(bad.status_code, 400)
        changed = self.client.patch(
            f"/api/v1/fee-plans/{plan.json()['id']}/",
            {"items": [{"head": self.tuition.pk, "amount_paise": 1600000}]},
            format="json",
        )
        self.assertEqual(changed.json()["total_paise"], 1600000)
        event = AuditEvent.objects.filter(action="fees.plan.saved").first()  # newest first
        self.assertEqual(event.details["after"], {"Tuition": 1600000})

    def test_accountants_read_but_do_not_change_setup(self):
        self.as_user(self.accountant)
        self.assertEqual(self.client.get("/api/v1/fee-heads/").status_code, 200)
        self.assertEqual(
            self.client.post(
                "/api/v1/fee-heads/", {"branch": self.a.pk, "name": "X", "code": "x"}
            ).status_code,
            403,
        )
        response = self.client.patch(
            f"/api/v1/fee-plans/{self.plan.pk}/", {"items": []}, format="json"
        )
        self.assertEqual(response.status_code, 403)
