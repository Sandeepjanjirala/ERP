"""Performance summary, CSV export and the activity log over the API."""

import csv
import io

from apps.audit.models import AuditEvent
from apps.core.testing import ApiTestCase


class PerformanceTests(ApiTestCase):
    def test_summary_counts_published_results_only(self):
        self.as_user(self.principal)
        empty = self.client.get("/api/v1/reports/performance/").json()
        self.assertEqual((empty["summary"]["count"], empty["subjects"]), (0, []))

        self.publish()  # Alice 80/100 (pass), Bob 30/100 (below the pass mark of 35)
        body = self.client.get("/api/v1/reports/performance/").json()
        self.assertEqual(body["summary"]["count"], 2)
        self.assertEqual(body["summary"]["passed"], 1)
        self.assertEqual(body["summary"]["percentage"], "55.0")
        self.assertEqual(
            [(s["branch"], s["name"], s["count"]) for s in body["subjects"]],
            [("North", "Mathematics", 2)],
        )

    def test_scope_and_roles(self):
        self.publish()
        self.as_user(self.foreign_teacher)  # South can't see North's results
        self.assertEqual(
            self.client.get("/api/v1/reports/performance/").json()["summary"]["count"], 0
        )
        self.as_user(self.admin)
        url = f"/api/v1/reports/performance/?branch={self.b.pk}"
        self.assertEqual(self.client.get(url).status_code, 404)  # same as the web page
        self.as_user(self.e1.student.user)
        self.assertEqual(self.client.get("/api/v1/reports/performance/").status_code, 403)


class ExportTests(ApiTestCase):
    def test_csv_matches_the_web_export_and_is_audited(self):
        self.publish()
        self.as_user(self.admin)
        response = self.client.get("/api/v1/reports/performance/export/", HTTP_ACCEPT="text/csv")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        self.assertEqual(rows[0][:3], ["Branch", "Class", "Student"])
        self.assertEqual(len(rows), 3)  # header, Alice, Bob
        event = AuditEvent.objects.get(action="report.exported")
        self.assertEqual(event.details, {"rows": 2})

    def test_students_cannot_export(self):
        self.as_user(self.e1.student.user)
        response = self.client.get("/api/v1/reports/performance/export/")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(AuditEvent.objects.filter(action="report.exported").exists())


class ActivityTests(ApiTestCase):
    def test_leaders_see_their_branch_newest_first(self):
        exam = self.publish()  # writes marks.saved, exam.submit and exam.publish events (North)
        self.as_user(self.principal)
        rows = self.client.get("/api/v1/activity/").json()["results"]
        self.assertEqual(rows[0]["action"], "exam.publish")
        self.assertEqual(rows[0]["actor"]["id"], self.principal.pk)
        self.assertEqual(rows[0]["details"]["to"], "published")
        self.assertIn(str(exam.title), rows[0]["target"])

        exam_only = self.client.get("/api/v1/activity/?action=exam.").json()["results"]
        self.assertEqual([r["action"] for r in exam_only], ["exam.publish", "exam.submit"])

        self.as_user(self.foreign_teacher)
        self.assertEqual(self.client.get("/api/v1/activity/").status_code, 403)
        self.as_user(self.root)
        everything = self.client.get("/api/v1/activity/").json()["results"]
        self.assertEqual(
            [r["action"] for r in everything], ["exam.publish", "exam.submit", "marks.saved"]
        )

    def test_other_branch_events_are_hidden(self):
        self.publish()
        AuditEvent.objects.create(actor=self.root, branch=self.b, action="test.south", target="x")
        self.as_user(self.admin)
        actions = [r["action"] for r in self.client.get("/api/v1/activity/").json()["results"]]
        self.assertNotIn("test.south", actions)
