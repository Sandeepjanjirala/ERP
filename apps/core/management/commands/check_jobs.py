import secrets
import time

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError

from apps.core.tasks import ping


class Command(BaseCommand):
    help = "Check that a Celery worker runs jobs: send one through Redis and wait for its answer."

    def add_arguments(self, parser):
        parser.add_argument("--timeout", type=float, default=30, help="Seconds to wait.")

    def handle(self, *args, timeout, **options):
        if settings.CELERY_TASK_ALWAYS_EAGER:
            raise CommandError(
                "REDIS_URL is not set, so jobs run inside each request and there is no worker "
                "to check."
            )
        token = secrets.token_hex(8)
        started = time.monotonic()
        ping.delay(token)
        while time.monotonic() - started < timeout:
            if cache.get(f"jobs-check:{token}") == "pong":
                elapsed = time.monotonic() - started
                self.stdout.write(self.style.SUCCESS(f"A worker ran the job in {elapsed:.2f}s."))
                return
            time.sleep(0.25)
        raise CommandError(f"No worker answered within {timeout:g}s. Is `celery worker` running?")
