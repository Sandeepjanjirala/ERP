from contextlib import contextmanager
from contextvars import ContextVar

from django.db import transaction

_paused = ContextVar("jobs_paused", default=False)


def run_after_commit(task, *args, **kwargs):
    """Queue a Celery task once the current database transaction commits.

    Services call this instead of task.delay(): a job never runs for a save that was rolled
    back, and never starts before the rows it reads are visible to the worker. Arguments must
    be plain values (ids, not model instances), because they travel through Redis.
    """
    if _paused.get():
        return
    transaction.on_commit(lambda: task.delay(*args, **kwargs))


@contextmanager
def jobs_paused():
    """Queue no background jobs inside this block.

    For bulk loads such as the demo seed, which records months of history at once: those
    registers and results must not send today's families hundreds of alerts and emails.
    """
    token = _paused.set(True)
    try:
        yield
    finally:
        _paused.reset(token)
