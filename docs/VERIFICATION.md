# Verification record

Build verified on 10 October 2026.

## Completed checks

| Check | Observed result |
|---|---|
| Python runtime | 3.12.14 |
| Django runtime | 5.2.18 |
| Application tests with `school.test_settings` | **57 passed; 2 PostgreSQL-only tests skipped** (59 discovered) |
| Earlier application test run using normal password hashing | 50 tests passed before the final contact-edit/reassignment additions |
| Django system checks | No issues |
| `makemigrations --check --dry-run` | No changes detected |
| `collectstatic --noinput` | CSS and JavaScript collected and hashed successfully |
| `node --check static/school/portal.js` | Passed |
| Production configuration `check --deploy` | No issues using non-debug settings, a fresh local random secret, an example HTTPS hostname and a placeholder PostgreSQL URL |

The production configuration check is a settings check. It does **not** establish database connectivity or verify an online host.

The application tests cover:

- Authentication, password hashing, forced password changes, password-reset email generation, CSRF enforcement and POST-only mutations.
- Login throttling, including Unicode-normalized usernames.
- Deactivated accounts and existing-session access revocation.
- Branch boundaries, teacher class/subject assignments and student self-only access.
- Forged role/branch fields in account creation and profile editing.
- Teacher reassignment preserving classroom/subject boundaries.
- Attendance completeness, future dates, duplicate prevention, correction reasons, before/after audit records and stale-form rejection.
- Mark validation, whole-sheet rollback, missing scores, locked marks and stale-form rejection.
- Principal-only publication, reopening and the exclusion of unpublished results from students.
- Attendance calculations, absence handling, no-data states, report scope and formula-safe CSV exports.
- Server rendering for supported role/page combinations and academic setup forms.
- Synthetic demo creation, refusing to overwrite existing data, and refusing production seeding.

## Not executed here

1. **PostgreSQL and its two concurrency tests.** PostgreSQL was not installed and the environment did not permit the system package installation. SQLite was used for the completed application tests. The provided GitHub Actions job and Docker test command run against PostgreSQL; neither has been executed on your account.
2. **Docker image build / Docker Desktop startup.** Docker was unavailable in this build environment.
3. **Interactive desktop/mobile browser QA.** No supported browser automation was available. Django's test client checked rendered HTTP responses; it does not test visual layout, client-side clicks, or browser printing.
4. **A live deployment, public DNS, HTTPS proxy behavior, real SMTP delivery, or backup/restore.** These need the selected hosting account and real configuration.

For those reasons, the delivered package is ready for **local evaluation**, with the PostgreSQL, browser and hosting checks still required before starting the staff/student pilot with real records.

## Reproduce

```text
python manage.py test --settings=school.test_settings --noinput
python manage.py makemigrations --check --dry-run
python manage.py collectstatic --noinput
```

After starting the supplied Docker/PostgreSQL setup:

```text
docker compose exec web python manage.py test --settings=school.test_settings --noinput
```

Use a disposable test database with permission to create/drop Django test databases. Keep that permission separate from the restricted runtime database account on your actual host.
