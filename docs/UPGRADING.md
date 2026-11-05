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

5. **Check:** sign in with an existing account, open a student report, and compare record counts with the old database. `convert_legacy_data` prints the count per model.

## What was verified

Rehearsed on 5 November 2026 with the real pre-Phase-1 development database. It was exported by the old code, then converted and loaded into PostgreSQL 17 by the new code.

- All 179 records arrived, with their IDs.
- Accounts signed in with their original passwords.
- A scripted walkthrough of 101 checks passed on the upgraded data:
  - every page for every role
  - attendance correction and stale-tab rejection
  - publish, reopen and resubmit of results
  - account creation with a forced password change
  - admission, CSV export, and branch and student isolation

`apps/core/tests/test_legacy_upgrade.py` keeps the conversion covered in CI.
