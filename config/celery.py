"""The Celery app. Workers start with `celery -A config worker`; the schedule with `... beat`.

Settings come from Django settings named CELERY_*; tasks are found in each app's tasks.py.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

app = Celery("edunexa")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
