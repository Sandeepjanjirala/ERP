# 7. Background jobs after commit, idempotent; cache keys that carry a data version

**Status:** Accepted, November 2026 (Phase 3)

## Context

Phase 3 sends things to people: absence alerts, results, leave decisions and announcements, in the app and by email. Email is slow and can fail, and an announcement can reach a whole branch, so this work must not run inside a web request. The dashboards also gain charts that aggregate every attendance row in scope.

The quick local setup runs on Windows, where Celery isn't supported, and must keep working with one command.

## Decision

**Celery with Redis.** Services queue jobs through `run_after_commit(task, ids...)`:

- A job runs only if the save that queued it committed. A rejected register, or one rolled back by an error, alerts nobody.
- Jobs receive ids, not objects, and re-read the database, so they see the committed state.
- Jobs are acknowledged when they finish (`acks_late`), so a worker that dies mid-job doesn't lose it. The price is that a job can run twice, so every job is idempotent: each notification has a key (`results:12:3`) that is unique per recipient in the database, and `notify()` skips anyone who already has it.
- Jobs re-check the facts before acting: a student corrected to present gets no absence alert; an exam reopened since gets no announcement.

**Without Redis, jobs run in the request**, right after the commit (`CELERY_TASK_ALWAYS_EAGER`). The same code path, minus the worker. Tests use this mode and run the after-commit callbacks explicitly.

**`jobs_paused()`** for bulk loads such as the demo seed, which records months of history in one go.

**Cache keys carry a data version.** Dashboard aggregates are cached under a key that includes a fingerprint of the registers in scope: their count plus the sum of their version numbers, read from the small registers table. Any save, correction or leave approval changes the fingerprint, so the next request computes fresh numbers. Nothing deletes keys, and a stale answer can't be served. An earlier version used the newest timestamp instead; on Windows two saves can share a clock tick, so the fingerprint uses no clock.

**The report card PDF is drawn on request**, not in a job: it takes milliseconds and the person is waiting for it. Jobs are for work that is slow, external or fans out to many people.

## Consequences

- Saving a register stays fast however many families must be told, and a failing mail server can't break saving.
- Production runs two more processes: a worker and exactly one `beat`. `manage.py check_jobs` (also run in CI against a real worker) proves the worker is taking jobs.
- Notifications are at-least-once internally but exactly-once to people, thanks to the unique key.
- A changed name can show on a dashboard list for up to an hour, until its cache entry expires; the numbers themselves are never stale.
