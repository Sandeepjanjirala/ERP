"""Adding parents to students, linking siblings, and the primary contact, on the web and API."""

from django.core.exceptions import PermissionDenied
from django.urls import reverse

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.core.testing import PASSWORD, ApiTestCase, SchoolTestCase
from apps.students.models import StudentGuardian
from apps.students.services import link_guardian, make_primary_guardian

NEW_PARENT = {
    "username": "Ravi.Father",
    "first_name": "Ravi",
    "last_name": "Kumar",
    "email": "ravi@example.com",
    "phone": "+91 98480 22338",
    "password": PASSWORD,
    "relationship": "father",
}


class GuardianWebTests(SchoolTestCase):
    """Web pages post HTML forms, so these use Django's own test client."""

    def setUp(self):
        self.client.force_login(self.admin)

    def test_admin_adds_a_new_parent_account(self):
        url = reverse("guardian_create", args=[self.e2.student.pk])  # Bob has no guardian yet
        response = self.client.post(url, NEW_PARENT)
        self.assertRedirects(response, reverse("student_report", args=[self.e2.student.pk]))
        parent = User.objects.get(username="ravi.father")
        self.assertEqual((parent.role, parent.branch), (User.Role.PARENT, self.a))
        self.assertTrue(parent.must_change_password)
        link = StudentGuardian.objects.get(guardian__user=parent)
        self.assertTrue(link.is_primary)  # Bob's first guardian
        self.assertTrue(AuditEvent.objects.filter(action="guardian.linked").exists())

    def test_link_a_sibling_and_change_the_primary_contact(self):
        url = reverse("guardian_link", args=[self.e2.student.pk])
        response = self.client.post(url, {"parent": self.parent.pk, "relationship": "mother"})
        self.assertEqual(response.status_code, 302)
        children = set(
            StudentGuardian.objects.filter(guardian__user=self.parent).values_list(
                "student_id", flat=True
            )
        )
        self.assertEqual(children, {self.e1.student.pk, self.e2.student.pk})

        # Alice gets a father too, then he becomes the primary contact.
        father = link_guardian(
            self.admin,
            self.e1.student,
            User.objects.create_user(
                "father", "father@example.com", PASSWORD, role="parent", branch=self.a
            ),
            "father",
        )
        self.assertFalse(father.is_primary)
        response = self.client.post(
            reverse("guardian_make_primary", args=[self.e1.student.pk, father.pk])
        )
        self.assertEqual(response.status_code, 302)
        primaries = StudentGuardian.objects.filter(student=self.e1.student, is_primary=True)
        self.assertEqual([link.pk for link in primaries], [father.pk])

    def test_report_page_lists_guardians_and_manager_actions(self):
        page = self.client.get(reverse("student_report", args=[self.e1.student.pk]))
        self.assertContains(page, "Primary contact")
        self.assertContains(page, reverse("guardian_create", args=[self.e1.student.pk]))
        self.client.force_login(self.teacher)
        page = self.client.get(reverse("student_report", args=[self.e1.student.pk]))
        self.assertContains(page, "Primary contact")
        self.assertNotContains(page, reverse("guardian_create", args=[self.e1.student.pk]))

    def test_who_may_manage_guardians(self):
        for user, status in ((self.teacher, 403), (self.principal, 403), (self.parent, 403)):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                url = reverse("guardian_create", args=[self.e2.student.pk])
                self.assertEqual(self.client.get(url).status_code, status)
        self.client.force_login(self.admin)
        other_branch = reverse("guardian_create", args=[self.foreign_enrollment.student.pk])
        self.assertEqual(self.client.get(other_branch).status_code, 404)

    def test_service_refuses_a_parent_from_another_branch(self):
        foreign_parent = User.objects.create_user(
            "southparent", "sp@example.com", PASSWORD, role="parent", branch=self.b
        )
        with self.assertRaises(PermissionDenied):
            link_guardian(self.root, self.e1.student, foreign_parent, "father")
        with self.assertRaises(PermissionDenied):
            make_primary_guardian(self.teacher, self.e1.student.guardian_links.get())


class GuardianApiTests(ApiTestCase):
    def url(self, student, suffix=""):
        return f"/api/v1/students/{student.pk}/guardians/{suffix}"

    def test_list_create_link_and_make_primary(self):
        self.as_user(self.teacher)  # staff can see contacts
        listed = self.client.get(self.url(self.e1.student)).json()
        self.assertEqual(
            [(g["guardian"]["username"], g["is_primary"]) for g in listed], [("parent", True)]
        )

        self.as_user(self.admin)
        created = self.client.post(self.url(self.e1.student), NEW_PARENT)
        self.assertEqual(created.status_code, 201, created.content)
        father = next(g for g in created.json() if g["guardian"]["username"] == "ravi.father")
        self.assertEqual((father["relationship"], father["is_primary"]), ("father", False))
        self.assertEqual(father["guardian"]["phone"], "+91 98480 22338")

        linked = self.client.post(
            self.url(self.e2.student, "link/"), {"parent": self.parent.pk, "relationship": "mother"}
        )
        self.assertEqual(linked.status_code, 201, linked.content)

        primary = self.client.post(self.url(self.e1.student, f"{father['id']}/make-primary/"))
        self.assertEqual(primary.status_code, 200)
        self.assertEqual(
            [g["guardian"]["username"] for g in primary.json() if g["is_primary"]], ["ravi.father"]
        )

        self.as_user(self.parent)
        children = self.client.get("/api/v1/me/").json()["children"]
        self.assertEqual(sorted(c["admission_number"] for c in children), ["ALICE", "BOB"])

    def test_api_roles(self):
        cases = [
            (self.teacher, "post", 403),
            (self.principal, "post", 403),
            (self.e1.student.user, "get", 403),
            (self.parent, "get", 403),
        ]
        for user, method, status in cases:
            with self.subTest(user=user.username, method=method):
                self.as_user(user)
                response = getattr(self.client, method)(self.url(self.e1.student), NEW_PARENT)
                self.assertEqual(response.status_code, status)
        self.as_user(self.admin)
        foreign = self.client.get(self.url(self.foreign_enrollment.student))
        self.assertEqual(foreign.status_code, 404)
        other_parent = User.objects.create_user(
            "southparent", "sp@example.com", PASSWORD, role="parent", branch=self.b
        )
        response = self.client.post(
            self.url(self.e1.student, "link/"),
            {"parent": other_parent.pk, "relationship": "father"},
        )
        self.assertIn("parent", response.json()["fields"])


class ParentAccountManagementTests(ApiTestCase):
    def test_admins_manage_parent_accounts_and_phone_numbers(self):
        self.as_user(self.admin)
        rows = {
            r["username"]: r
            for r in self.client.get("/api/v1/people/?role=parent").json()["results"]
        }
        self.assertTrue(rows["parent"]["can_edit"])
        response = self.client.patch(
            f"/api/v1/people/{self.parent.pk}/", {"phone": "+91 90000 11111"}
        )
        self.assertEqual(response.json()["phone"], "+91 90000 11111")
        bad = self.client.patch(f"/api/v1/people/{self.parent.pk}/", {"phone": "call me"})
        self.assertEqual(bad.status_code, 400)
