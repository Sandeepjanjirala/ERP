from celery import shared_task

from .services import reset_demo


@shared_task
def reset_demo_nightly():
    """Scheduled at 03:45 in demo mode only (config/settings/base.py)."""
    reset_demo()
