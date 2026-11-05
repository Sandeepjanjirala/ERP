"""Exams over the API: scoped lists, creation rules, mark sheets and the result workflow."""

from apps.audit.models import AuditEvent
from apps.core.testing import ApiTestCase
from apps.exams.models import Exam


def titles(response):
    return sorted(row["title"] for row in response.json()["results"])


class ExamListTests(ApiTestCase):
    def test_each_role_sees_its_own_exams(self):
        cases = [
            (self.root, ["Midterm", "Private south exam", "Science test"]),
            (self.principal, ["Midterm", "Science test"]),
            (self.teacher, ["Midterm", "Science test"]),  # homeroom: every subject in the class
            (self.other_teacher, ["Science test"]),  # only the assigned subject
            (self.e1.student.user, []),  # nothing is published yet
        ]
        for user, expected in cases:
            with self.subTest(user=user.username):
                self.as_user(user)
                self.assertEqual(titles(self.client.get("/api/v1/exams/")), expected)

    def test_students_see_published_results_only(self):
        self.publish()
        self.as_user(self.e1.student.user)
        self.assertEqual(titles(self.client.get("/api/v1/exams/")), ["Midterm"])
        self.assertEqual(self.client.get(f"/api/v1/exams/{self.science_exam.pk}/").status_code, 404)

    def test_status_filter_and_out_of_scope_detail(self):
        self.as_user(self.root)
        self.assertEqual(
            titles(self.client.get("/api/v1/exams/?status=draft")),
            ["Midterm", "Private south exam", "Science test"],
        )
        self.assertEqual(titles(self.client.get("/api/v1/exams/?status=published")), [])
        self.as_user(self.teacher)
        self.assertEqual(self.client.get(f"/api/v1/exams/{self.foreign_exam.pk}/").status_code, 404)

    def test_actions_come_from_the_same_policy_as_the_web_buttons(self):
        self.as_user(self.teacher)
        actions = self.client.get(f"/api/v1/exams/{self.exam.pk}/").json()["actions"]
        self.assertEqual(
            actions,
            {"can_edit_marks": True, "can_submit": True, "can_publish": False, "can_reopen": False},
        )
        self.as_user(self.principal)
        actions = self.client.get(f"/api/v1/exams/{self.exam.pk}/").json()["actions"]
        self.assertFalse(any(actions.values()))  # nothing to approve while it's a draft


class ExamCreateTests(ApiTestCase):
    def body(self, **overrides):
        return {
            "classroom": self.c.pk,
            "subject": self.math.pk,
            "title": "Unit test 1",
            "date": self.today.isoformat(),
            "max_marks": "25",
            "pass_marks": "10",
            **overrides,
        }

    def test_assigned_teacher_creates_a_draft(self):
        self.as_user(self.teacher)
        response = self.client.post("/api/v1/exams/", self.body())
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["status"], Exam.Status.DRAFT)
        self.assertEqual(response.json()["version"], 1)
        self.assertTrue(AuditEvent.objects.filter(action="exam.created").exists())

    def test_creation_rules(self):
        cases = [
            # (user, body changes, status, error field)
            # Someone else's subject: the service's can_create_exam policy refuses it.
            (self.teacher, {"subject": self.science.pk}, 403, None),
            # Principals approve results; they don't author exams (role check).
            (self.principal, {}, 403, None),
            # A class outside their scope isn't even a valid choice.
            (self.teacher, {"classroom": self.foreign_class.pk}, 400, "classroom"),
            # Pass mark above the maximum: the model's validation.
            (self.admin, {"pass_marks": "30"}, 400, None),
        ]
        for user, changes, status, field in cases:
            with self.subTest(user=user.username, changes=changes):
                self.as_user(user)
                response = self.client.post("/api/v1/exams/", self.body(**changes))
                self.assertEqual(response.status_code, status, response.content)
                if field:
                    self.assertIn(field, response.json()["fields"])
        self.assertFalse(Exam.objects.filter(title="Unit test 1").exists())

    def test_duplicate_exam_is_rejected(self):
        self.as_user(self.admin)
        duplicate = self.body(title="Midterm")
        response = self.client.post("/api/v1/exams/", duplicate)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid")


class MarkSheetTests(ApiTestCase):
    def url(self, exam=None):
        return f"/api/v1/exams/{(exam or self.exam).pk}/marks/"

    def body(self, version, alice="80", bob="30", bob_absent=False):
        return {
            "version": version,
            "marks": [
                {"enrollment": self.e1.pk, "score": alice},
                {"enrollment": self.e2.pk, "score": bob, "absent": bob_absent},
            ],
        }

    def test_read_and_save_the_sheet(self):
        self.as_user(self.teacher)
        sheet = self.client.get(self.url()).json()
        self.assertEqual([row["score"] for row in sheet["students"]], [None, None])

        saved = self.client.put(self.url(), self.body(1, bob=None, bob_absent=True))
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertEqual(saved.json()["exam"]["version"], 2)
        rows = saved.json()["students"]
        self.assertEqual(
            [(r["score"], r["absent"]) for r in rows], [("80.00", False), (None, True)]
        )

    def test_mark_rules_are_enforced(self):
        self.as_user(self.teacher)
        cases = [
            (self.body(1, alice="101"), 400),  # above the maximum
            (self.body(1, bob_absent=True), 400),  # a score and absent together
            (self.body(0), 400),  # version must be at least 1
        ]
        for body, status in cases:
            with self.subTest(body=body):
                self.assertEqual(self.client.put(self.url(), body).status_code, status)
        self.assertFalse(self.exam.marks.exists())

    def test_stale_version_conflicts(self):
        self.as_user(self.teacher)
        self.client.put(self.url(), self.body(1))
        response = self.client.put(self.url(), self.body(1, alice="90"))
        self.assertEqual(response.status_code, 409)

    def test_who_may_read_and_write_marks(self):
        self.as_user(self.e1.student.user)
        self.publish()
        self.assertEqual(self.client.get(self.url()).status_code, 403)  # the whole class's marks

        self.as_user(self.other_teacher)  # teaches science, not maths
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        science = self.url(self.science_exam)  # out of 50
        self.assertEqual(self.client.put(science, self.body(1, alice="40")).status_code, 200)
        self.as_user(self.admin)  # admins set up exams but don't enter marks
        self.assertEqual(self.client.put(science, self.body(2, alice="40")).status_code, 403)


class WorkflowTests(ApiTestCase):
    def post(self, action, version, reason=""):
        return self.client.post(
            f"/api/v1/exams/{self.exam.pk}/{action}/", {"version": version, "reason": reason}
        )

    def test_draft_to_published_and_back(self):
        exam = self.fill()  # complete marks, version 2
        self.as_user(self.teacher)
        submitted = self.post("submit", exam.version)
        self.assertEqual(submitted.status_code, 200, submitted.content)
        self.assertEqual(submitted.json()["status"], "submitted")
        version = submitted.json()["version"]

        locked = self.client.put(
            f"/api/v1/exams/{self.exam.pk}/marks/",
            {"version": version, "marks": [{"enrollment": self.e1.pk, "score": "1"}]},
        )
        self.assertEqual(locked.status_code, 400)
        self.assertEqual(self.post("publish", version).status_code, 403)  # teachers can't publish

        self.as_user(self.principal)
        published = self.post("publish", version)
        self.assertEqual(published.json()["status"], "published")
        self.assertEqual(published.json()["published_by"]["id"], self.principal.pk)
        version = published.json()["version"]

        self.assertEqual(self.post("reopen", version).status_code, 400)  # a reason is required
        reopened = self.post("reopen", version, reason="Marking error in question 4")
        self.assertEqual(reopened.json()["status"], "draft")
        self.assertEqual(
            list(
                AuditEvent.objects.filter(action__startswith="exam.")
                .order_by("pk")
                .values_list("action", flat=True)
            ),
            ["exam.submit", "exam.publish", "exam.reopen"],
        )

    def test_incomplete_marks_cannot_be_submitted(self):
        self.as_user(self.teacher)
        response = self.post("submit", self.exam.version)
        self.assertEqual(response.status_code, 400)
        self.assertIn("every enrolled student", response.json()["detail"])

    def test_stale_transition_conflicts(self):
        exam = self.fill()
        self.as_user(self.teacher)
        self.assertEqual(self.post("submit", exam.version - 1).status_code, 409)
