"""Background jobs run only after the save that queued them has committed."""

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.test import TestCase

from apps.core.jobs import jobs_paused, run_after_commit

ran = []


@shared_task
def record(value):
    ran.append(value)


class RunAfterCommitTests(TestCase):
    def setUp(self):
        ran.clear()

    def test_the_job_waits_for_the_commit(self):
        with self.captureOnCommitCallbacks(execute=True):
            run_after_commit(record, 1)
            self.assertEqual(ran, [])  # still inside the transaction
        self.assertEqual(ran, [1])

    def test_a_rolled_back_save_queues_nothing(self):
        class Failed(Exception):
            pass

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            try:
                with transaction.atomic():
                    run_after_commit(record, 2)
                    raise Failed
            except Failed:
                pass
        self.assertEqual((ran, callbacks), ([], []))

    def test_paused_jobs_are_not_queued(self):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with jobs_paused():
                run_after_commit(record, 3)
            run_after_commit(record, 4)  # after the block, jobs queue again
        self.assertEqual((ran, len(callbacks)), ([4], 1))

    def test_the_schedule_names_real_tasks(self):
        from config.celery import app

        app.loader.import_default_modules()
        for entry in settings.CELERY_BEAT_SCHEDULE.values():
            with self.subTest(task=entry["task"]):
                self.assertIn(entry["task"], app.tasks)
