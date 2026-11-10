"""manage.py check_jobs: the worker health check used by CI and by operators."""

from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from apps.core.tasks import ping


class CheckJobsTests(SimpleTestCase):
    def test_without_redis_there_is_no_worker_to_check(self):
        with self.assertRaisesMessage(CommandError, "REDIS_URL is not set"):
            call_command("check_jobs", stdout=StringIO())

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    def test_a_worker_that_answers(self):
        # Stand in for the worker: run the job as soon as it is sent.
        with mock.patch.object(ping, "delay", side_effect=lambda token: ping(token)):
            out = StringIO()
            call_command("check_jobs", "--timeout", "2", stdout=out)
        self.assertIn("A worker ran the job", out.getvalue())

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    def test_no_worker(self):
        with mock.patch.object(ping, "delay"):  # sent, but nobody runs it
            with self.assertRaisesMessage(CommandError, "No worker answered"):
                call_command("check_jobs", "--timeout", "0.5", stdout=StringIO())
