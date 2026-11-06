from celery import shared_task
from django.core.cache import cache


@shared_task
def ping(token):
    """Answer `manage.py check_jobs`: proves a worker took a job off the queue and ran it."""
    cache.set(f"jobs-check:{token}", "pong", timeout=60)
