"""A parent sees their own children and nothing else: not classmates, not drafts, not staff pages.

The fixture's parent is Alice's mother. Bob is in Alice's class but is not her child.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse

from apps.academics.selectors import classrooms
from apps.accounts.models import User
from apps.accounts.tests.factories import UserFactory
from apps.attendance.selectors import attendance_rows
from apps.attendance.services import save_register
from apps.core.testing import ApiTestCase
from apps.exams.selectors import exams
from apps.students.models import Guardian, StudentGuardian
from apps.students.selectors import enrollments, guardian_links, students


class ParentSelectorTests(ApiTestCase):
    def test_reads_are_limited_to_the_children(self):
        self.assertEqual(list(classrooms(self.parent)), [self.c])
        self.assertEqual(list(students(self.parent)), [self.e1.student])
        self.assertEqual(list(enrollments(self.parent)), [self.e1])  # not Bob's
        self.assertEqual([link.student for link in guardian_links(self.parent)], [self.e1.student])

    def test_only_published_results_the_child_sat(self):
        self.assertEqual(list(exams(self.parent)), [])  # nothing published yet
        self.publish()  # Midterm; the science test stays a draft
        self.assertEqual(list(exams(self.parent)), [self.exam])

    def test_attendance_is_the_childs_only(self):
        save_register(self.teacher, self.c, self.today, {self.e1.pk: "P", self.e2.pk: "A"}, 0)
        rows = attendance_rows(self.parent)
        self.assertEqual([row.enrollment_id for row in rows], [self.e1.pk])


class ParentWebTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.publish()
        self.client.force_login(self.parent)

    def test_overview_is_the_childs_dashboard(self):
        response = self.client.get(reverse("dashboard"))
        self.assertTemplateUsed(response, "reports/family_dashboard.html")
        self.assertEqual(response.context["student"], self.e1.student)
        classmate = self.client.get(reverse("dashboard") + f"?child={self.e2.student.pk}")
        self.assertEqual(classmate.status_code, 404)

    def test_child_report_yes_classmate_no(self):
        self.assertEqual(
            self.client.get(reverse("student_report", args=[self.e1.student.pk])).status_code, 200
        )
        self.assertEqual(
            self.client.get(reverse("student_report", args=[self.e2.student.pk])).status_code, 404
        )

    def test_exam_pages_show_the_childs_results_not_the_class_sheet(self):
        page = self.client.get(reverse("exams")).content.decode()
        self.assertIn("Midterm", page)
        self.assertNotIn("Science test", page)  # a draft
        response = self.client.get(reverse("exam_detail", args=[self.exam.pk]))
        self.assertRedirects(response, reverse("student_report", args=[self.e1.student.pk]))
        draft = self.client.get(reverse("exam_detail", args=[self.science_exam.pk]))
        self.assertEqual(draft.status_code, 404)

    def test_staff_pages_are_forbidden_and_hidden(self):
        for name in ("students", "attendance", "reports", "users", "setup", "audit", "exam_create"):
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)
        sidebar = self.client.get(reverse("exams")).content.decode()
        self.assertNotIn(reverse("attendance"), sidebar)
        self.assertNotIn(reverse("students"), sidebar)

    def test_a_parent_without_linked_children_sees_a_message(self):
        self.parent.guardian_profile.child_links.all().delete()
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "No children are linked")


class ParentApiTests(ApiTestCase):
    def test_api_scope(self):
        self.publish()
        self.as_user(self.parent)
        classes = self.client.get("/api/v1/classrooms/").json()["results"]
        self.assertEqual([c["id"] for c in classes], [self.c.pk])
        titles = [e["title"] for e in self.client.get("/api/v1/exams/").json()["results"]]
        self.assertEqual(titles, ["Midterm"])
        own = f"/api/v1/students/{self.e1.student.pk}/report/"
        classmate = f"/api/v1/students/{self.e2.student.pk}/report/"
        self.assertEqual(self.client.get(own).status_code, 200)
        self.assertEqual(self.client.get(classmate).status_code, 404)
        self.assertEqual(self.client.get(f"/api/v1/exams/{self.exam.pk}/marks/").status_code, 403)

    def test_me_lists_the_children(self):
        self.as_user(self.parent)
        me = self.client.get("/api/v1/me/").json()
        self.assertEqual((me["role"], me["student_id"]), ("parent", None))
        self.assertEqual(
            me["children"],
            [
                {
                    "student_id": self.e1.student.pk,
                    "name": "alice",
                    "admission_number": "ALICE",
                    "relationship": "mother",
                    "is_primary": True,
                }
            ],
        )
        self.as_user(self.teacher)
        self.assertEqual(self.client.get("/api/v1/me/").json()["children"], [])


class GuardianModelTests(ApiTestCase):
    def test_guardian_rules(self):
        guardian = self.parent.guardian_profile
        cases = [
            # A guardian profile needs a parent account.
            lambda: Guardian.objects.create(user=self.teacher),
            # A second primary guardian for Alice.
            lambda: StudentGuardian.objects.create(
                student=self.e1.student,
                guardian=Guardian.objects.create(
                    user=UserFactory(role=User.Role.PARENT, branch=self.a)
                ),
                relationship="father",
                is_primary=True,
            ),
            # A child in another branch.
            lambda: StudentGuardian.objects.create(
                student=self.foreign_enrollment.student,
                guardian=guardian,
                relationship="mother",
            ),
        ]
        for number, create in enumerate(cases):
            with self.subTest(case=number), self.assertRaises(ValidationError):
                with transaction.atomic():
                    create()
