from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.accounts.forms import AccountForm
from apps.accounts.models import User
from apps.core.testing import PASSWORD, SchoolTestCase


class AccountManagementTests(SchoolTestCase):
    """Creating and editing accounts without privilege escalation."""

    def test_admin_cannot_create_or_promote_admin_principal(self):
        data = {
            "username": "malicious",
            "first_name": "Mallory",
            "email": "malicious@example.com",
            "password": PASSWORD,
            "role": "principal",
            "branch": self.a.pk,
        }
        form = AccountForm(data, actor=self.admin)
        self.assertFalse(form.is_valid())
        self.assertIn("role", form.errors)
        self.sign_in(self.admin)
        self.assertEqual(
            self.client.post(reverse("toggle_user", args=[self.principal.pk])).status_code, 403
        )

    def test_admin_cannot_create_cross_branch_user(self):
        form = AccountForm(
            {
                "username": "someone",
                "first_name": "Someone",
                "email": "someone@example.com",
                "password": PASSWORD,
                "role": "teacher",
                "branch": self.b.pk,
            },
            actor=self.admin,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("branch", form.errors)

    def test_create_teacher_uses_hashed_password_and_forces_change(self):
        self.sign_in(self.admin)
        response = self.client.post(
            reverse("user_create"),
            {
                "username": "newteacher",
                "first_name": "New",
                "last_name": "Teacher",
                "email": "newteacher@example.com",
                "password": PASSWORD,
                "role": "teacher",
                "branch": self.a.pk,
            },
        )
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="newteacher")
        self.assertTrue(user.check_password(PASSWORD))
        self.assertTrue(user.must_change_password)
        self.assertFalse(user.is_superuser)

    def test_roles_require_matching_branch_and_privileges(self):
        user = User(
            username="broken",
            email="broken@example.com",
            role="teacher",
            branch=self.a,
            is_superuser=True,
        )
        with self.assertRaises(ValidationError):
            user.save()

    def test_user_edit_ignores_role_and_branch_escalation(self):
        self.sign_in(self.admin)
        response = self.client.post(
            reverse("user_edit", args=[self.teacher.pk]),
            {
                "first_name": "Updated",
                "last_name": "Teacher",
                "email": self.teacher.email,
                "role": "superadmin",
                "branch": self.b.pk,
                "is_superuser": "true",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.teacher.refresh_from_db()
        self.assertEqual(self.teacher.first_name, "Updated")
        self.assertEqual(self.teacher.role, "teacher")
        self.assertEqual(self.teacher.branch_id, self.a.pk)
        self.assertFalse(self.teacher.is_superuser)

    def test_user_edit_forbidden_for_principal_and_foreign_users(self):
        self.sign_in(self.admin)
        self.assertEqual(
            self.client.get(reverse("user_edit", args=[self.principal.pk])).status_code, 403
        )
        self.assertEqual(
            self.client.get(reverse("user_edit", args=[self.foreign_teacher.pk])).status_code, 404
        )

    def test_duplicate_username_different_case_rejected(self):
        with self.assertRaises(ValidationError):
            User.objects.create_user(
                "TEACHER", "different@example.com", PASSWORD, role="teacher", branch=self.a
            )
