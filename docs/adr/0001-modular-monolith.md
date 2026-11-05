# 1. One Django project split into layered domain apps

**Status:** Accepted, November 2026 (Phase 1)

## Context

All models, views, forms and tests lived in one `school` app, including a 400-line `views.py` and a 450-line `tests.py`. Fees, timetables, notifications and an API are coming, and in that layout every change would touch the same few files.

Microservices would split the code too, but they bring network calls, distributed transactions and several deployments. The core workflows rely on database transactions across tables, such as locking a classroom while saving its register.

## Decision

Keep one Django project and one database (a *modular monolith*), split into ten domain apps under `apps/`. `INSTALLED_APPS` lists them from the lowest layer to the highest, and an app may import only from apps listed before it.

Where a lower app needs data from a higher one, it reads through reverse relations instead of importing it. For example, `students` checks `classroom.exams` without importing `exams`.

The restructure started a fresh migration history (one `0001_initial` per app), which was safe because there was no production data.

## Consequences

- Each app is small and reads the same way. A new feature, such as `fees`, gets its own app.
- No import cycles, and the dependency direction is visible in one list.
- Transactions and joins across apps keep working, with one deployment.
- The layering is a convention. It is not enforced by a tool yet, so code review has to watch for imports going the wrong way.
