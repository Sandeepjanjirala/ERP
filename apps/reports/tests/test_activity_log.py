"""Activity log filters, and the request id that ties a response to the entries it wrote."""

import re
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from apps.academics.models import Subject
from apps.audit.models import AuditEvent
from apps.audit.services import audit
from apps.core.testing import ApiTestCase


class RequestIdTests(ApiTestCase):
    def test_entries_carry_the_id_of_the_request_that_wrote_them(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("setup_create", args=["subject"]),
            {"branch": self.a.pk, "name": "History", "code": "history"},
            format="multipart",
            HTTP_X_REQUEST_ID="forged-id-from-client",
        )
        request_id = response["X-Request-ID"]
        self.assertRegex(request_id, r"^[0-9a-f]{32}$")  # ours, not the client's
        event = AuditEvent.objects.get(action="setup.subject.saved")
        self.assertEqual(event.request_id, request_id)
        self.assertTrue(Subject.objects.filter(code="history").exists())
        # Outside a request (a job, a command, this test) there is no id.
        audit(self.admin, self.a, "test.outside", "x")
        self.assertEqual(AuditEvent.objects.get(action="test.outside").request_id, "")
        # Each request gets its own.
        self.assertNotEqual(self.client.get(reverse("dashboard"))["X-Request-ID"], request_id)


class ActivityFilterTests(ApiTestCase):
    def setUp(self):
        audit(self.admin, self.a, "exam.publish", "Midterm · 9-A")
        audit(self.teacher, self.a, "attendance.saved", "9-A register")
        audit(self.admin, self.a, "fees.payment.recorded", "#12 Term 1")
        audit(self.root, self.b, "exam.publish", "South exam")
        audit(self.principal, self.a, "exam.reopen", "Old exam")
        AuditEvent.objects.filter(action="exam.reopen").update(
            created_at=timezone.now() - timedelta(days=40), request_id="0" * 32
        )
        self.client.force_login(self.admin)

    def actions(self, **query):
        page = self.client.get(reverse("audit"), query)
        return sorted(event.action for event in page.context["page_obj"])

    def test_each_filter(self):
        today = timezone.localdate()
        self.assertEqual(self.actions(area="exam"), ["exam.publish", "exam.reopen"])
        self.assertEqual(self.actions(person="teacher"), ["attendance.saved"])
        self.assertEqual(self.actions(text="term 1"), ["fees.payment.recorded"])
        self.assertEqual(
            self.actions(since=(today - timedelta(days=50)).isoformat(), until=(today - timedelta(days=30)).isoformat()),
            ["exam.reopen"],
        )  # fmt: skip
        self.assertEqual(self.actions(request="0" * 32), ["exam.reopen"])
        # Filters combine, and the branch rule still applies: South's exam never shows.
        self.assertEqual(self.actions(area="exam", person="admin"), ["exam.publish"])
        page = self.client.get(reverse("audit"), {"area": "exam"})
        self.assertIn("exam", [value for value, _ in page.context["form"].fields["area"].choices])
        self.assertContains(page, 'hx-select="#results"')

    def test_a_backwards_date_range_is_explained(self):
        today = timezone.localdate()
        page = self.client.get(
            reverse("audit"),
            {"since": today.isoformat(), "until": (today - timedelta(days=1)).isoformat()},
        )
        self.assertContains(page, "The start date must be on or before the end date.")

    def test_api_filters(self):
        self.as_user(self.admin)
        today = timezone.localdate().isoformat()
        rows = self.client.get("/api/v1/activity/", {"since": today, "action": "exam."}).json()[
            "results"
        ]
        self.assertEqual([row["action"] for row in rows], ["exam.publish"])
        rows = self.client.get("/api/v1/activity/", {"request_id": "0" * 32}).json()["results"]
        self.assertEqual([row["target"] for row in rows], ["Old exam"])
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]*", row["request_id"]) for row in rows))
