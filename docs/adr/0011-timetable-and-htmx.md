# 11. Timetable clashes stopped by the database; htmx without loosening the CSP

**Status:** Accepted, November 2026 (Phase 5)

## Context

A weekly timetable must never put a class in two lessons at once, or a teacher in two classes at once. Two admins may edit two classes' timetables at the same moment. Phase 5 also brings the first in-page updates (saving a timetable cell, one-tap attendance, filtering lists as you type). The Content-Security-Policy forbids inline scripts and `eval`, and must stay that way.

## Decision

**Two unique constraints in the database**, so no code path can break the rule:

- `class_once_per_period`: (classroom, weekday, period).
- `teacher_once_per_period`: (teacher, year, weekday, period). The slot copies its classroom's year so this can be a plain constraint.

**`save_lesson` locks the classroom row**, so edits to one class run one at a time, and checks the teacher first so the person gets a clear message ("... already teaches 9-A on Monday in Period 1"). Two admins booking one teacher into two different classes don't share a lock. There the database refuses the second insert, and the service turns that into the same message. This is tested on PostgreSQL with real threads.

**htmx 2.0.4**, vendored and checked against its published hash, like Chart.js:

- Its config turns off `eval`, inline scripts and injected styles, and allows same-origin requests only. EduNexa never uses `hx-on` or `js:`. The CSP is unchanged.
- Requests carry the CSRF token in a header set on `<body>`.
- Every htmx form is also a normal form. Without JavaScript it posts and the page reloads.
- Partial responses come from the same views, and errors come back with status 200, because htmx swaps in only successful responses.
- Live filters use `hx-select`: htmx asks for the same page and keeps only the results. The server filters exactly as before.

## Consequences

- A clash can't be saved by any route: page, API, script or a race.
- The interactive pages work, and are tested, with and without JavaScript.
- New interactive features follow the same pattern; anything needing `hx-on` or inline script would need a new decision.
