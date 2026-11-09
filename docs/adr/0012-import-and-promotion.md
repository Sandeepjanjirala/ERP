# 12. Bulk changes: a dry-run preview, then all or nothing

**Status:** Accepted, November 2026 (Phase 5)

## Context

Two Phase 5 features change many records at once. A CSV import admits up to 500 students with their guardians. Year-end promotion moves a whole class into the next year. A half-finished bulk change is the hardest kind of mistake to repair, and both are often clicked twice.

## Decision

**CSV import: check with the real code, then roll back.** The check runs every row through the ordinary services (`admit_student`, `add_guardian_account`, `link_guardian`), each in its own savepoint, inside one transaction that is then rolled back.

- The preview lists exactly the problems an import would hit, row by row, including clashes between rows of the same file (two rows with one email). It needs no second set of validation rules that could drift from the first.
- Confirming locks the batch and replays the rows in one transaction. If anything changed since the check, nothing is imported and the batch shows the new problems.
- An imported batch is never imported again.
- File limits: 2 MB, 500 rows, UTF-8, known columns only (a misspelt column is refused, not ignored).
- New accounts get a random password nobody sees. A background job emails each one a link to set their own password, and the batch records when, so a retried job sends nothing twice.

**Promotion: one transaction, with explicit decisions.**

- Every student needs a decision (move up, repeat, leave). The page suggests one for each, but nothing happens to a whole class by default.
- The classes are locked in id order. Old enrollments close on the year's last day, and new ones start on the next year's first day.
- A student already enrolled in a later year is skipped, so a second run, or two leaders at once, moves each student once. This is tested on PostgreSQL with real threads.

## Consequences

- An import or promotion is either fully done or not done at all, and repeating it is harmless.
- The import's check is as slow as a real import (every row is really saved, then undone), which is fine at 500 rows.
- Both are permission-checked in their services (managers import; principals and admins promote) and audited.
