from apps.accounts.selectors import people
from apps.audit.models import AuditEvent
from apps.audit.services import audit
from apps.core.testing import SchoolTestCase
from apps.exams.models import Exam


class StableOrderingTests(SchoolTestCase):
    """Paginated lists end their ordering with a unique column, so pages never repeat or skip rows."""

    def test_paginated_lists_have_a_unique_tie_breaker(self):
        self.assertEqual(people(self.root).query.order_by[-1], "username")
        self.assertEqual(people(self.admin).query.order_by[-1], "username")
        self.assertEqual(Exam._meta.ordering[-1], "pk")
        self.assertEqual(AuditEvent._meta.ordering[-1], "-pk")

    def test_audit_event_without_details_is_valid(self):
        audit(self.admin, self.a, "account.login", self.admin.username)
        AuditEvent.objects.latest("pk").full_clean()  # used to fail: details {} counted as blank
