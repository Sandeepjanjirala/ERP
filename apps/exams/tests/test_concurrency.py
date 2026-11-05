from decimal import Decimal

from apps.audit.models import AuditEvent
from apps.core.testing import ConcurrentTestCase
from apps.exams.models import Mark
from apps.exams.services import save_marks


class ConcurrentMarkTests(ConcurrentTestCase):
    """Two people saving the same mark sheet at once."""

    def test_concurrent_mark_updates_reject_stale_writer(self):
        self.race(
            lambda actor, index: save_marks(
                actor,
                self.exam,
                {
                    self.e1.pk: (Decimal(70 + index), False),
                    self.e2.pk: (Decimal(70 + index), False),
                },
                1,
            )
        )
        self.assertEqual(Mark.objects.count(), 2)
        self.assertEqual(len(set(Mark.objects.values_list("score", flat=True))), 1)
        self.assertEqual(AuditEvent.objects.filter(action="marks.saved").count(), 1)
