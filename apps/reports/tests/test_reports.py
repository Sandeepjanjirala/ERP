from django.urls import reverse

from apps.attendance.models import Attendance
from apps.attendance.selectors import attendance_summary
from apps.audit.models import AuditEvent
from apps.core.testing import SchoolTestCase
from apps.exams.models import Mark
from apps.exams.selectors import mark_summary


class ReportTests(SchoolTestCase):
    """Scoped, audited exports and summary calculations."""

    def test_csv_export_scoped_and_audited(self):
        self.publish()
        Mark.objects.create(exam=self.foreign_exam, enrollment=self.foreign_enrollment, score=99)
        self.foreign_exam.status = "published"
        self.foreign_exam.save()
        self.sign_in(self.admin)
        response = self.client.get(reverse("reports") + "?format=csv")
        self.assertEqual(response.status_code, 200)
        self.assertIn("alice", response.content.decode())
        self.assertNotIn("charlie", response.content.decode())
        self.assertTrue(AuditEvent.objects.filter(action="report.exported").exists())

    def test_csv_formula_neutralization(self):
        from apps.reports.views import safe_csv

        self.assertEqual(safe_csv('=HYPERLINK("x")'), '\'=HYPERLINK("x")')

    def test_branch_query_tampering_denied(self):
        self.sign_in(self.admin)
        self.assertEqual(self.client.get("/reports/?branch=" + str(self.b.pk)).status_code, 404)

    def test_no_data_is_no_percentage(self):
        self.assertIsNone(attendance_summary(Attendance.objects.none())["rate"])
        self.assertIsNone(mark_summary([])["percentage"])
