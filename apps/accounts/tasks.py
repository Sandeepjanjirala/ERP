from datetime import timedelta

from celery import shared_task
from django.core.management import call_command
from django.utils import timezone

from .models import LoginAttempt


@shared_task
def flush_expired_tokens():
    """Daily: drop expired API refresh tokens from the blacklist table, and sign-in attempt
    counters whose 15-minute window is long over (attempts on made-up usernames would
    otherwise pile up)."""
    call_command("flushexpiredtokens")
    LoginAttempt.objects.filter(started_at__lt=timezone.now() - timedelta(days=1)).delete()
