# Upgrading data from the single-app version

Phase 1 split the old `school` app into domain apps and started a fresh migration history (see [ADR 0001](adr/0001-modular-monolith.md)). Database tables were renamed, for example `school_user` became `accounts_user`, so running `migrate` on a database created by the old code **does not** carry its records across.

The models' fields did not change, so the data moves with Django's own fixture tools. Primary keys, password hashes and every relation are kept. Sign-in throttle counters (`LoginAttempt`) are temporary and are not copied.

## Steps

1. **Back up** the old database first.
2. **Export with the old code** (the commit before Phase 1), pointed at the old database:

   ```powershell
   python -X utf8 manage.py dumpdata school --indent 2 -o legacy.json
   ```

   On Windows, `-X utf8` matters: without it, `dumpdata -o` writes in the system code page and characters such as "·" break the file.

3. **Switch to the new code** and create an empty database (a new PostgreSQL database, or a new SQLite file), then build the schema:

   ```powershell
   python manage.py migrate
   ```

4. **Convert and load:**

   ```powershell
   python -X utf8 manage.py convert_legacy_data legacy.json upgraded.json
   python manage.py loaddata upgraded.json
   ```

   `loaddata` also resets the PostgreSQL ID sequences, so new records don't collide with the loaded ones.

   Since Phase 5 the converter also creates the records the old app didn't have: one grade per (branch, grade name), ordered by the number in the name, and two terms per year with each exam placed in the term of its date, the same rules as the Phase 5 migrations.

5. **Check:** sign in with an existing account, open a student report, and compare record counts with the old database. `convert_legacy_data` prints the count per model.

## What was verified

Rehearsed on 5 November 2026 with the real pre-Phase-1 development database. It was exported by the old code, then converted and loaded into PostgreSQL 17 by the new code. Three independent comparisons:

| Check | Result |
|---|---|
| **Records:** the upgraded database re-exported and compared with the old export | 179 of 179 records. All 943 field values are identical, including 374 foreign-key and relation values, timestamps and audit-log details. |
| **Permissions:** for each of the 21 users, the old code on the old database versus the new code on the upgraded database | No differences in visible branches, classrooms, students, enrollments, exams, attendance, people and activity log; in which registers they may record and which exams they may mark or publish; or in which accounts they may edit or deactivate |
| **Validation:** `full_clean()` on every loaded row, because `loaddata` skips model validation while loading | 179 of 179 valid |

A scripted walkthrough of 101 checks then passed on the upgraded data:

- every page for every role
- attendance correction and stale-tab rejection
- publish, reopen and resubmit of results
- account creation with a forced password change
- admission, CSV export, and branch and student isolation

The rehearsal found two small bugs, both present before Phase 1 and both fixed without touching stored data (the migrations are database no-ops):

- **Unstable list order.** The people list, exam list and activity log ordered rows only by columns that can tie, so a page could repeat or skip a row. Each ordering now ends with a unique column.
- **Empty audit details.** Audit events with empty `details` failed validation because the field didn't allow blank values.

`apps/core/tests/test_legacy_upgrade.py` and `test_stable_ordering.py` keep both covered in CI.
