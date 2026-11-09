"""The versioned grading scale: drafts use the newest version, published results keep theirs."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.core.testing import ApiTestCase, pdf_text
from apps.exams.models import Mark
from apps.exams.selectors import current_scale
from apps.exams.services import DEFAULT_BANDS, save_grading_scale, transition_exam
from apps.reports.selectors import student_report

CBSE = [{"label": label, "min_percent": minimum} for label, minimum in DEFAULT_BANDS]
# A stricter scale: 80% is a C now, not a B1.
STRICT = [
    {"label": "A", "min_percent": 90},
    {"label": "B", "min_percent": 85},
    {"label": "C", "min_percent": 50},
    {"label": "F", "min_percent": 0},
]


class GradingScaleTests(ApiTestCase):
    def alice_report(self):
        return student_report(self.admin, self.e1.student)

    def test_results_published_with_a_scale_keep_it(self):
        save_grading_scale(self.root, CBSE)
        self.publish()  # Alice 80/100, Bob 30/100
        report = self.alice_report()
        self.assertEqual(report["marks"][0].grade_label, "B1")
        self.assertEqual(report["summary"]["grade"], "B1")
        self.assertEqual(self.exam.grading_scale.version, 1)

        save_grading_scale(self.root, STRICT)  # version 2
        report = self.alice_report()
        self.assertEqual(report["marks"][0].grade_label, "B1")  # unchanged: published with v1
        self.assertEqual(report["summary"]["grade"], "B1")

    def test_drafts_use_the_newest_version_and_republishing_takes_it(self):
        save_grading_scale(self.root, CBSE)
        exam = self.publish()
        save_grading_scale(self.root, STRICT)
        transition_exam(self.principal, exam, "reopen", exam.version, "Correcting a mark")
        exam.refresh_from_db()
        self.assertIsNone(exam.grading_scale)  # a draft again: no frozen scale
        mark = Mark.objects.select_related("exam").get(exam=exam, enrollment=self.e1)
        self.assertEqual(mark.grade(current_scale()), "C")  # the draft shows the newest version
        transition_exam(self.teacher, exam, "submit", exam.version)
        exam.refresh_from_db()
        transition_exam(self.principal, exam, "publish", exam.version)
        self.assertEqual(self.alice_report()["marks"][0].grade_label, "C")
        event = AuditEvent.objects.filter(action="exam.publish").first()  # newest first
        self.assertEqual(event.details["grading_scale"], 2)

    def test_results_published_before_any_scale_never_gain_a_grade(self):
        self.publish()
        save_grading_scale(self.root, CBSE)
        report = self.alice_report()
        self.assertIsNone(report["marks"][0].grade_label)
        self.assertIsNone(report["summary"]["grade"])

    def test_a_scale_must_be_complete_and_unambiguous(self):
        cases = {
            "one band": ([{"label": "A", "min_percent": 0}], "at least two bands"),
            "no 0% band": ([{"label": "A", "min_percent": 50}, {"label": "B", "min_percent": 10}], "lowest band must start at 0%"),
            "same label": ([{"label": "A", "min_percent": 50}, {"label": "a", "min_percent": 0}], "its own label"),
            "same start": ([{"label": "A", "min_percent": 0}, {"label": "B", "min_percent": 0}], "same percentage"),
            "over 100": ([{"label": "A", "min_percent": 101}, {"label": "B", "min_percent": 0}], "0 to 100"),
        }  # fmt: skip
        for case, (rows, message) in cases.items():
            with self.subTest(case=case), self.assertRaisesMessage(ValidationError, message):
                save_grading_scale(self.root, rows)
        self.assertIsNone(current_scale())

    def test_only_super_admins_change_the_scale(self):
        for user in (self.admin, self.principal):
            with self.subTest(user=user.username), self.assertRaises(PermissionDenied):
                save_grading_scale(user, CBSE)
        save_grading_scale(self.root, CBSE)
        event = AuditEvent.objects.get(action="exams.grading_scale.saved")
        self.assertEqual(event.details["version"], 1)
        self.assertIn("A1 from 91%", event.details["bands"])

    def test_the_grading_page(self):
        save_grading_scale(self.root, CBSE)
        url = reverse("grading_scale")
        self.client.force_login(self.principal)
        page = self.client.get(url)
        self.assertContains(page, "91% to 100%")
        self.assertIsNone(page.context["formset"])  # principals read it only
        self.assertEqual(self.client.post(url, {}).status_code, 403)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.root)
        form = {"form-TOTAL_FORMS": "4", "form-INITIAL_FORMS": "0"}
        for n, row in enumerate(STRICT):
            form |= {f"form-{n}-label": row["label"], f"form-{n}-min_percent": row["min_percent"]}
        self.assertRedirects(self.client.post(url, form, format="multipart"), url)
        self.assertEqual(current_scale().version, 2)
        bad = {**form, "form-3-min_percent": "5"}  # no band starts at 0%
        page = self.client.post(url, bad, format="multipart")
        self.assertContains(page, "lowest band must start at 0%")

    def test_api_and_report_card(self):
        save_grading_scale(self.root, CBSE)
        self.publish()
        self.as_user(self.teacher)
        versions = self.client.get("/api/v1/grading-scales/").json()["results"]
        self.assertEqual(
            versions[0]["bands"][0], {"label": "A1", "min_percent": "91.00", "below_percent": None}
        )
        body = {"bands": STRICT}
        self.assertEqual(
            self.client.post("/api/v1/grading-scales/", body, format="json").status_code, 403
        )
        self.as_user(self.root)
        created = self.client.post("/api/v1/grading-scales/", body, format="json")
        self.assertEqual((created.status_code, created.json()["version"]), (201, 2))
        self.as_user(self.parent)
        report = self.client.get(f"/api/v1/students/{self.e1.student_id}/report/").json()
        self.assertEqual((report["results"][0]["grade"], report["summary"]["grade"]), ("B1", "B1"))
        card = self.client.get(
            f"/api/v1/students/{self.e1.student_id}/report-card/", HTTP_ACCEPT="application/pdf"
        )
        self.assertIn("grade B1", pdf_text(card.content))
