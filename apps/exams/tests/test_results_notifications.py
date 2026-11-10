"""Publishing results tells the students who sat the exam and their guardians."""

from django.core import mail

from apps.communication.models import Notification
from apps.core.testing import SchoolTestCase
from apps.exams.services import transition_exam
from apps.exams.tasks import announce_results


def told(exam):
    return sorted(
        Notification.objects.filter(key__startswith=f"results:{exam.pk}:").values_list(
            "recipient__username", flat=True
        )
    )


class ResultsNotificationTests(SchoolTestCase):
    def submit(self):
        exam = self.fill()
        transition_exam(self.teacher, exam, "submit", exam.version)
        exam.refresh_from_db()
        return exam

    def publish_now(self, exam):
        with self.captureOnCommitCallbacks(execute=True):
            exam = transition_exam(self.principal, exam, "publish", exam.version)
        return exam

    def test_publishing_tells_students_and_guardians(self):
        exam = self.publish_now(self.submit())
        self.assertEqual(told(exam), ["alice", "bob", "parent"])
        self.assertEqual(len(mail.outbox), 3)
        self.assertIn("Midterm", mail.outbox[0].subject)

    def test_submitting_tells_nobody(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.submit()
        self.assertEqual(Notification.objects.count(), 0)

    def test_republishing_after_a_reopen_tells_them_again(self):
        exam = self.publish_now(self.submit())
        with self.captureOnCommitCallbacks(execute=True):
            exam = transition_exam(self.principal, exam, "reopen", exam.version, "Typo in Q3")
        exam = transition_exam(self.teacher, exam, "submit", exam.version)
        self.publish_now(exam)
        self.assertEqual(Notification.objects.filter(recipient=self.parent).count(), 2)

    def test_a_reopened_exam_is_not_announced_by_a_late_job(self):
        exam = self.publish_now(self.submit())
        published_version = exam.version
        transition_exam(self.principal, exam, "reopen", exam.version, "Typo in Q3")
        Notification.objects.all().delete()
        self.assertEqual(announce_results(exam.pk, published_version), 0)
