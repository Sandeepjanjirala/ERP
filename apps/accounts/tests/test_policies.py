from django.core.exceptions import PermissionDenied

from apps.accounts.policies import can_change_access, can_manage_account
from apps.accounts.services import toggle_access, update_contact_details
from apps.core.testing import SchoolTestCase


class AccountPolicyTests(SchoolTestCase):
    """The who-may-change-which-account matrix, checked directly rather than through pages."""

    def test_manage_account_matrix(self):
        student = self.e1.student.user
        cases = [
            # (actor, person, allowed)
            (self.root, self.admin, True),
            (self.root, self.principal, True),
            (self.root, self.foreign_teacher, True),
            (self.root, self.root, False),  # super admin accounts are never managed here
            (self.admin, self.teacher, True),
            (self.admin, student, True),
            (self.admin, self.principal, False),  # only super admins manage principals
            (self.admin, self.foreign_teacher, False),  # another branch
            (self.admin, self.root, False),
            (self.principal, self.teacher, False),  # principals don't manage accounts
            (self.teacher, student, False),
            (student, self.teacher, False),
        ]
        for actor, person, allowed in cases:
            with self.subTest(actor=actor.username, person=person.username):
                self.assertEqual(can_manage_account(actor, person), allowed)

    def test_nobody_can_deactivate_themselves(self):
        self.assertTrue(can_change_access(self.admin, self.teacher))
        self.assertFalse(can_change_access(self.root, self.root))
        self.assertFalse(can_change_access(self.admin, self.admin))

    def test_services_recheck_permissions(self):
        # Services enforce the policy too, so a new caller (such as an API view) can't skip it.
        with self.assertRaises(PermissionDenied):
            toggle_access(self.admin, self.principal)
        with self.assertRaises(PermissionDenied):
            update_contact_details(self.principal, self.teacher)
        self.teacher.refresh_from_db()
        self.assertTrue(self.teacher.is_active)
