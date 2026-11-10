"""Academic setup over the API: the same setup services, policy and audit as the web pages."""

from datetime import timedelta

from apps.academics.models import AcademicYear, Classroom, Subject, TeachingAssignment
from apps.audit.models import AuditEvent
from apps.core.testing import ApiTestCase
from apps.organization.models import Branch


class GroupLevelSetupTests(ApiTestCase):
    def test_super_admin_adds_a_branch_and_a_year(self):
        self.as_user(self.root)
        branch = self.client.post(
            "/api/v1/branches/", {"name": "East", "code": "east", "city": "Guntur"}
        )
        self.assertEqual(branch.status_code, 201, branch.content)
        self.assertEqual(Branch.objects.get(code="east").organization_id, self.org.pk)

        starts = self.year.ends_on + timedelta(days=1)
        year = self.client.post(
            "/api/v1/years/",
            {
                "name": "Next year",
                "starts_on": starts.isoformat(),
                "ends_on": (starts + timedelta(days=300)).isoformat(),
            },
        )
        self.assertEqual(year.status_code, 201, year.content)
        self.assertEqual(
            sorted(AuditEvent.objects.values_list("action", flat=True)),
            ["setup.branch.saved", "setup.year.saved"],
        )

    def test_group_level_records_are_for_super_admins(self):
        self.as_user(self.admin)
        response = self.client.post(
            "/api/v1/branches/", {"name": "East", "code": "east", "city": "Guntur"}
        )
        self.assertEqual(response.status_code, 403)  # the setup policy, inside the service
        self.as_user(self.principal)
        self.assertEqual(self.client.post("/api/v1/years/", {}).status_code, 403)  # role
        self.assertFalse(Branch.objects.filter(code="east").exists())

    def test_year_rules_come_from_the_model(self):
        self.as_user(self.root)
        response = self.client.post(
            "/api/v1/years/",
            {"name": "Backwards", "starts_on": "2027-06-01", "ends_on": "2027-01-01"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(AcademicYear.objects.filter(name="Backwards").exists())

    def test_organization_name(self):
        self.as_user(self.teacher)
        self.assertEqual(self.client.get("/api/v1/organization/").json()["name"], self.org.name)
        self.assertEqual(self.client.patch("/api/v1/organization/", {"name": "X"}).status_code, 403)
        self.as_user(self.root)
        renamed = self.client.patch("/api/v1/organization/", {"name": "Greenfield Group"})
        self.assertEqual(renamed.json()["name"], "Greenfield Group")
        self.org.refresh_from_db()
        self.assertEqual(self.org.name, "Greenfield Group")


class BranchSetupTests(ApiTestCase):
    def test_branch_admin_sets_up_a_classroom_subject_and_assignment(self):
        self.as_user(self.admin)
        grade = self.client.post(
            "/api/v1/grades/", {"branch": self.a.pk, "name": "10", "order": 10}
        )
        self.assertEqual(grade.status_code, 201, grade.content)
        classroom = self.client.post(
            "/api/v1/classrooms/",
            {
                "branch": self.a.pk,
                "year": self.year.pk,
                "grade_id": grade.json()["id"],
                "section": "B",
                "homeroom_teacher": self.other_teacher.pk,
            },
        )
        self.assertEqual(classroom.status_code, 201, classroom.content)
        self.assertEqual(classroom.json()["homeroom_teacher"]["id"], self.other_teacher.pk)
        # The name stays in `grade`, as before grades were records; `grade_id` is new.
        self.assertEqual(
            (classroom.json()["grade"], classroom.json()["grade_id"]), ("10", grade.json()["id"])
        )

        subject = self.client.post(
            "/api/v1/subjects/", {"branch": self.a.pk, "name": "History", "code": "history"}
        )
        self.assertEqual(subject.status_code, 201, subject.content)

        assignment = self.client.post(
            "/api/v1/assignments/",
            {
                "teacher": self.teacher.pk,
                "classroom": classroom.json()["id"],
                "subject": subject.json()["id"],
            },
        )
        self.assertEqual(assignment.status_code, 201, assignment.content)
        self.assertEqual(
            AuditEvent.objects.filter(action__startswith="setup.", branch=self.a).count(), 4
        )

    def test_choices_are_limited_to_the_branch(self):
        self.as_user(self.admin)
        cases = [
            ("/api/v1/subjects/", {"branch": self.b.pk, "name": "X", "code": "x"}, "branch"),
            (
                "/api/v1/classrooms/",
                {
                    "branch": self.a.pk,
                    "year": self.year.pk,
                    "grade_id": self.grade9.pk,
                    "section": "C",
                    "homeroom_teacher": self.foreign_teacher.pk,
                },
                "homeroom_teacher",
            ),
            (
                "/api/v1/classrooms/",
                {
                    "branch": self.a.pk,
                    "year": self.year.pk,
                    "grade_id": self.foreign_grade9.pk,  # South's grade: out of scope
                    "section": "D",
                },
                "grade_id",
            ),
            ("/api/v1/grades/", {"branch": self.b.pk, "name": "11", "order": 11}, "branch"),
            (
                "/api/v1/assignments/",
                {
                    "teacher": self.teacher.pk,
                    "classroom": self.foreign_class.pk,
                    "subject": self.math.pk,
                },
                "classroom",
            ),
        ]
        for url, body, field in cases:
            with self.subTest(url=url):
                response = self.client.post(url, body)
                self.assertEqual(response.status_code, 400, response.content)
                self.assertIn(field, response.json()["fields"])

    def test_duplicates_are_rejected_by_the_model(self):
        self.as_user(self.admin)
        response = self.client.post(
            "/api/v1/subjects/", {"branch": self.a.pk, "name": "Maths again", "code": "math"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Subject.objects.filter(branch=self.a, code="math").count(), 1)

    def test_principals_and_teachers_cannot_change_setup(self):
        for user in (self.principal, self.teacher):
            with self.subTest(user=user.username):
                self.as_user(user)
                response = self.client.post(
                    "/api/v1/subjects/", {"branch": self.a.pk, "name": "Art", "code": "art"}
                )
                self.assertEqual(response.status_code, 403)


class SetupEditTests(ApiTestCase):
    def test_assignment_edit_changes_only_the_teacher(self):
        """The same guarantee as the web edit page: class and subject can't move."""
        assignment = TeachingAssignment.objects.get(teacher=self.teacher, subject=self.math)
        self.as_user(self.admin)
        response = self.client.patch(
            f"/api/v1/assignments/{assignment.pk}/",
            {
                "teacher": self.other_teacher.pk,
                "classroom": self.foreign_class.pk,
                "subject": self.foreign_subject.pk,
            },
        )
        self.assertEqual(response.status_code, 200, response.content)
        assignment.refresh_from_db()
        self.assertEqual(
            (assignment.teacher_id, assignment.classroom_id, assignment.subject_id),
            (self.other_teacher.pk, self.c.pk, self.math.pk),
        )
        event = AuditEvent.objects.get(action="setup.assignment.updated")
        self.assertEqual(event.details["changed_fields"], ["teacher"])

    def test_classroom_edit_keeps_branch_and_year(self):
        # A real, valid other year: if `year` were writable, this would move the classroom.
        other_year = AcademicYear.objects.create(
            name="Other year",
            starts_on=self.year.ends_on + timedelta(days=1),
            ends_on=self.year.ends_on + timedelta(days=300),
        )
        self.as_user(self.admin)
        response = self.client.patch(
            f"/api/v1/classrooms/{self.c.pk}/",
            {"section": "Z", "branch": self.b.pk, "year": other_year.pk},
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.c.refresh_from_db()
        self.assertEqual(
            (self.c.section, self.c.branch_id, self.c.year_id), ("Z", self.a.pk, self.year.pk)
        )

    def test_other_branch_records_are_not_found(self):
        self.as_user(self.admin)
        for url in (
            f"/api/v1/classrooms/{self.foreign_class.pk}/",
            f"/api/v1/subjects/{self.foreign_subject.pk}/",
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.patch(url, {"name": "x"}).status_code, 404)
        self.assertEqual(Classroom.objects.get(pk=self.foreign_class.pk).section, "B")

    def test_branches_and_years_are_not_editable(self):
        self.as_user(self.root)
        self.assertEqual(
            self.client.patch(f"/api/v1/branches/{self.a.pk}/", {"name": "x"}).status_code, 405
        )
        self.assertEqual(
            self.client.patch(f"/api/v1/years/{self.year.pk}/", {"name": "x"}).status_code, 405
        )
