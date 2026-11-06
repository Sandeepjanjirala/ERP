"""People & access over the API: the same account policies as the web page."""

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.core.testing import PASSWORD, ApiTestCase


class PeopleListTests(ApiTestCase):
    def test_who_may_list_people(self):
        for user, status in (
            (self.root, 200),
            (self.admin, 200),
            (self.principal, 200),
            (self.teacher, 403),
            (self.e1.student.user, 403),
        ):
            with self.subTest(user=user.username):
                self.as_user(user)
                self.assertEqual(self.client.get("/api/v1/people/").status_code, status)

    def test_branch_scope_and_row_actions(self):
        self.as_user(self.admin)
        rows = {row["username"]: row for row in self.client.get("/api/v1/people/?page_size=100")
                .json()["results"]}  # fmt: skip
        self.assertNotIn("foreignteacher", rows)  # another branch
        self.assertNotIn("root", rows)
        self.assertEqual(
            (rows["teacher"]["can_edit"], rows["teacher"]["can_toggle_access"]), (True, True)
        )
        self.assertEqual(
            (rows["principal"]["can_edit"], rows["principal"]["can_toggle_access"]), (False, False)
        )
        self.assertEqual(
            (rows["admin"]["can_edit"], rows["admin"]["can_toggle_access"]), (False, False)
        )

    def test_role_filter(self):
        self.as_user(self.root)
        rows = self.client.get("/api/v1/people/?role=teacher").json()["results"]
        self.assertEqual(
            sorted(r["username"] for r in rows), ["foreignteacher", "otherteacher", "teacher"]
        )


class StaffAccountCreateTests(ApiTestCase):
    def body(self, **overrides):
        return {
            "username": "NewTeacher",
            "first_name": "Neha",
            "last_name": "Rao",
            "email": "Neha@Example.com",
            "role": "teacher",
            "password": PASSWORD,
            **overrides,
        }

    def test_branch_admin_creates_a_teacher_in_their_own_branch(self):
        self.as_user(self.admin)
        response = self.client.post("/api/v1/people/", self.body())
        self.assertEqual(response.status_code, 201, response.content)
        person = User.objects.get(username="newteacher")  # stored lower-case, like the web form
        self.assertEqual(person.email, "neha@example.com")
        self.assertEqual(person.branch, self.a)
        self.assertTrue(person.must_change_password)
        self.assertNotIn("password", response.json())
        self.assertTrue(AuditEvent.objects.filter(action="account.created").exists())

    def test_creation_rules(self):
        cases = [
            # (actor, body changes, status, field with the error)
            (self.admin, {"role": "principal"}, 400, "role"),  # only super admins create principals
            (self.admin, {"role": "student"}, 400, "role"),  # students come through admission
            (self.admin, {"branch": self.b.pk}, 400, "branch"),  # another branch: not a choice
            (self.root, {"role": "principal"}, 400, "branch"),  # super admins must pick a branch
            (self.admin, {"username": "TEACHER"}, 400, "username"),  # taken, ignoring case
            (self.admin, {"email": "TEACHER@example.com"}, 400, "email"),
            (self.admin, {"password": "short"}, 400, None),  # Django's password validators
            (self.principal, {}, 403, None),  # principals don't manage accounts
        ]
        for actor, changes, status, field in cases:
            with self.subTest(actor=actor.username, changes=changes):
                self.as_user(actor)
                response = self.client.post("/api/v1/people/", self.body(**changes))
                self.assertEqual(response.status_code, status, response.content)
                if field:
                    self.assertIn(field, response.json()["fields"])
        self.assertFalse(User.objects.filter(username="newteacher").exists())

    def test_super_admin_creates_a_principal_in_a_chosen_branch(self):
        self.as_user(self.root)
        response = self.client.post(
            "/api/v1/people/", self.body(role="principal", branch=self.b.pk)
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["branch"]["id"], self.b.pk)


class AccountChangeTests(ApiTestCase):
    def test_contact_edit_changes_only_name_and_email(self):
        self.as_user(self.admin)
        response = self.client.patch(
            f"/api/v1/people/{self.teacher.pk}/",
            {"first_name": "Tara", "role": "admin", "branch": self.b.pk, "username": "x"},
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.teacher.refresh_from_db()
        self.assertEqual(self.teacher.first_name, "Tara")
        # Unknown fields are ignored: role, branch and username stay as they were.
        self.assertEqual(
            (self.teacher.role, self.teacher.branch, self.teacher.username),
            ("teacher", self.a, "teacher"),
        )
        self.assertTrue(AuditEvent.objects.filter(action="account.profile_updated").exists())

    def test_email_change(self):
        self.as_user(self.admin)
        response = self.client.patch(
            f"/api/v1/people/{self.teacher.pk}/", {"email": "Tara.New@Example.com"}
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.teacher.refresh_from_db()
        self.assertEqual(self.teacher.email, "tara.new@example.com")  # stored lower-case

    def test_contact_edit_rules(self):
        self.as_user(self.admin)
        taken = self.client.patch(
            f"/api/v1/people/{self.teacher.pk}/", {"email": "principal@example.com"}
        )
        self.assertIn("email", taken.json()["fields"])
        self.assertEqual(
            self.client.patch(
                f"/api/v1/people/{self.principal.pk}/", {"first_name": "P"}
            ).status_code,
            403,  # in the branch, but only super admins manage principals
        )
        self.assertEqual(
            self.client.patch(
                f"/api/v1/people/{self.foreign_teacher.pk}/", {"first_name": "F"}
            ).status_code,
            404,  # another branch
        )
        self.as_user(self.principal)
        self.assertEqual(
            self.client.patch(
                f"/api/v1/people/{self.teacher.pk}/", {"first_name": "T"}
            ).status_code,
            403,
        )

    def test_put_is_not_offered(self):
        self.as_user(self.admin)
        response = self.client.put(f"/api/v1/people/{self.teacher.pk}/", {"first_name": "T"})
        self.assertEqual(response.status_code, 405)

    def test_toggle_access(self):
        self.as_user(self.admin)
        url = f"/api/v1/people/{self.teacher.pk}/toggle-access/"
        self.assertFalse(self.client.post(url).json()["is_active"])
        self.assertTrue(self.client.post(url).json()["is_active"])
        self.assertEqual(
            self.client.post(f"/api/v1/people/{self.admin.pk}/toggle-access/").status_code,
            403,  # never your own account
        )
        self.assertEqual(
            list(
                AuditEvent.objects.filter(action__startswith="account.")
                .order_by("pk")
                .values_list("action", flat=True)
            ),
            ["account.deactivated", "account.activated"],
        )
