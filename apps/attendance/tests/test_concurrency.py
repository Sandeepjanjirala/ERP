from apps.attendance.models import Attendance, AttendanceSession
from apps.attendance.services import save_register
from apps.audit.models import AuditEvent
from apps.core.testing import ConcurrentTestCase


class ConcurrentRegisterTests(ConcurrentTestCase):
    """Two people saving the same new register at once."""

    def test_concurrent_register_creation_cannot_duplicate_or_overwrite(self):
        self.race(
            lambda actor, index: save_register(
                actor, self.c, self.today, {self.e1.pk: "P" if index else "A", self.e2.pk: "P"}, 0
            )
        )
        self.assertEqual(AttendanceSession.objects.count(), 1)
        self.assertEqual(Attendance.objects.count(), 2)
        self.assertEqual(AuditEvent.objects.filter(action="attendance.saved").count(), 1)
