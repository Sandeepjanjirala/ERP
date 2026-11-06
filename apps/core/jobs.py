from django.db import transaction


def run_after_commit(task, *args, **kwargs):
    """Queue a Celery task once the current database transaction commits.

    Services call this instead of task.delay(): a job never runs for a save that was rolled
    back, and never starts before the rows it reads are visible to the worker. Arguments must
    be plain values (ids, not model instances), because they travel through Redis.
    """
    transaction.on_commit(lambda: task.delay(*args, **kwargs))
