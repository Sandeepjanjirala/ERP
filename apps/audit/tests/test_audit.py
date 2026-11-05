from apps.audit.services import audit
from apps.core.testing import SchoolTestCase


class AuditTests(SchoolTestCase):
    """Branch-scoped activity log."""

    def test_audit_scope(self):
        audit(self.foreign_teacher, self.b, "private.change", "South private target")
        self.sign_in(self.admin)
        self.assertNotContains(self.client.get("/activity/"), "South private target")
