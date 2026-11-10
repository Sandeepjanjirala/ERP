# EduNexa

**School ERP for school groups with many branches, built with Django.**

[![CI](https://github.com/Sandeepjanjirala/edunexa/actions/workflows/ci.yml/badge.svg)](https://github.com/Sandeepjanjirala/edunexa/actions/workflows/ci.yml)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue)
![Django 5.2 LTS](https://img.shields.io/badge/django-5.2%20LTS-0C4B33)
![PostgreSQL 17](https://img.shields.io/badge/postgresql-17-336791)

EduNexa runs the daily work of a school group: branches, classrooms and teachers, timetables, daily attendance, exams with a principal-approval workflow, fees with online payments, a parent portal, reports and performance analysis. Every role sees only what it is responsible for, and every important change is recorded in an activity log. Everything is also available through a documented REST API, and the whole stack (HTTPS, PostgreSQL, Redis, Celery) is ready to deploy on one Linux server.

![Overview dashboard](docs/screenshots/dashboard.png)

| One-tap attendance (teacher) | Exam review (principal) |
|---|---|
| ![Daily attendance register](docs/screenshots/attendance.png) | ![Exam review](docs/screenshots/exam-review.png) |
| **Weekly timetable (admin)** | **Student report (dark theme)** |
| ![Timetable editing](docs/screenshots/timetable.png) | ![Student report in dark mode](docs/screenshots/student-report-dark.png) |
| **Search with Ctrl+K** | **Parent portal on a phone** |
| ![Global search](docs/screenshots/search.png) | ![Parent overview on a phone](docs/screenshots/parent-phone.png) |

## What it does

- **Seven roles:** super admin, branch admin, principal, teacher, accountant, student and parent. Each sees only its own branch, classes, records or children; accountants see fees and nothing academic.
- **Daily attendance:** one register per class per day, one tap per student (or "mark all present"), saved without reloading the page. Every student must be marked, corrections need a reason, before/after values are logged, and families alerted about an absence are told if it is corrected the same day.
- **Timetable and academic year:** grades and terms per branch and year, each branch's periods, and a weekly timetable per class in which the database refuses a class or a teacher booked twice in one period. Teachers see their week and today's lessons.
- **Exams and results:** teachers enter marks, then the workflow runs Draft → Submitted → Published. Only principals publish, and reopening a published exam needs a reason. Each exam sits in the term of its date, and results carry a grade (A1 ... E) from a versioned grading scale that never changes a result already published.
- **Parents:** parent accounts linked to one or more children, with a primary contact. Parents follow attendance and results, download report cards, and apply for leave, which the class teacher approves.
- **Admissions and year end:** import students and their guardians from a CSV with a full preview (all rows saved together, or none), and move a class on at the end of the year in one go (move up, repeat or leave), safe to run twice.
- **Fees and payments:** fee plans per grade, invoices, concessions, cash/UPI/cheque at the office, and online payment through Razorpay (test mode) or a built-in Sandbox. Receipts are numbered without gaps and emailed as PDFs; overdue families get a weekly reminder; finance staff get a collection report with CSV. No real money moves.
- **Notifications:** a notification bell (it refreshes itself) and email for absences, published results, leave decisions and announcements, sent in the background.
- **Students who leave:** an admin records the last day. The student's sign-in stops the next day; parents keep access for a grace period (30 days, or 90 while fees are owed) to download a ZIP of every report card, the fee statement and receipts. Nothing is deleted.
- **Search:** Ctrl+K from any page finds students, people and invoices, each limited to what you may see.
- **Dashboards:** for each role, with attendance charts, students below 75% attendance, and what is waiting for you.
- **Reports:** report-card PDFs, printable student reports, subject performance analysis, and CSV exports scoped to your access and protected against spreadsheet formula injection.
- **Security:** login throttling, a forced password change on first sign-in, accounts switched off lose their sessions and tokens at once, a strict Content-Security-Policy (no inline scripts or styles), HSTS and secure cookies, and signed-in pages are never cached. See [SECURITY.md](docs/SECURITY.md).
- **A public demo mode:** one-click logins for every role, a nightly reset to fresh synthetic data, no real emails and Sandbox payments only. The reset refuses any database the demo didn't create.
- **Interface:** light and dark themes, responsive down to phone width, and keyboard and screen-reader friendly.
- **REST API:** every feature under `/api/v1/` (password reset by email stays a web flow), with JWT sign-in, Swagger UI at `/api/docs/` and ReDoc at `/api/redoc/`. See [API.md](docs/API.md).

## Engineering highlights

| What | How |
|---|---|
| No lost updates | Registers and mark sheets carry a version number, and writes lock the classroom row. Two people saving at once gives one save and one "reload" message, tested with real threads on PostgreSQL. |
| Rules the database enforces | One register per class per day, scores never above the maximum, valid role/branch combinations, no class or teacher booked twice in one timetable period: these are constraints in the database, not just form checks. |
| Bulk changes that are all or nothing | A CSV import is checked by running every row through the real services and rolling back; confirming replays them in one transaction. Promotion locks the classes and skips students already moved, so a double click or two leaders at once move each student once. See [ADR 0012](docs/adr/0012-import-and-promotion.md). |
| Business logic outside views | Each domain app has `selectors` (reads already limited to the user's scope), `policies` (who may do what) and `services` (writes with transactions, locks and audit). Views only parse input and render output. |
| One set of rules for web and API | The web pages and the REST API call the same selectors, policies and services, and every service checks its own policy, so the two can't disagree. See [ADR 0006](docs/adr/0006-rest-api.md). |
| Careful API security | 15-minute access tokens; refresh tokens that rotate and are blacklisted after use; a password change or deactivation revokes tokens; one sign-in limit shared with the web; out-of-scope records are 404. |
| Background jobs done properly | Celery and Redis. Jobs are queued only after the database commits, are safe to run twice (each notification has a unique key), and re-check the facts before acting. CI starts a real worker and checks it takes jobs. See [ADR 0007](docs/adr/0007-background-jobs-and-caching.md). |
| Payments done carefully | Money in integer paise. A payment is recorded only on a provider-signed webhook (HMAC, constant-time check) or a verified checkout whose amount is fetched from the provider. A repeated event records nothing; money beyond the balance is kept as excess, never discarded. Receipt numbers come from a locked counter inside the payment's transaction, so they are gapless. See [ADR 0008](docs/adr/0008-payments.md). |
| Data migrations tested on real copies | Turning grade text into records and placing every exam in a term ran on copies of existing databases with every row compared before and after, and the migrations run backwards too. See [ADR 0009](docs/adr/0009-grades-and-terms.md). |
| Caching that can't go stale | Dashboard numbers are cached in Redis under keys that include a fingerprint of the registers, so any change gives a new key. |
| No N+1 queries | A test measures each API list's SQL queries with few rows and with many; the count must not change. |
| Layered apps | Eleven apps ordered by dependency, with no circular imports, enforced by an import-linter contract on every test run. See [ARCHITECTURE.md](docs/ARCHITECTURE.md). |
| Production ready, and rehearsed | Caddy (automatic HTTPS) in front of Gunicorn, Celery and PostgreSQL in [`deploy/`](deploy/). Production refuses to start with incomplete settings. A script builds that stack locally under production settings and checks HTTPS, headers and cookies, runs the API checks, crawls every role's pages in a real browser, and runs a backup and restore drill that compares every table. See [DEPLOYMENT.md](docs/DEPLOYMENT.md). |
| Tested in a real browser | Playwright drives Chromium against the real Content-Security-Policy: one-tap attendance, timetable editing, live filters, Ctrl+K search, the bell, dialogs, charts, keyboard use and phone layouts. A crawl opens every page for every role and fails on any console error. |
| Saves that scale | A register or mark sheet is checked row by row, then written in bulk, in the same number of queries for 5 students or 50 (a test checks this). |
| Tested | 446 tests (plus 938 table-driven cases, such as every API endpoint for every role) with 95% branch coverage. CI runs them on PostgreSQL along with lint, a migration check, an OpenAPI schema check, a real Celery worker taking a job through Redis, and a Docker build. |

## Run it on your computer

You need **Python 3.12**. These commands are for Windows PowerShell; on macOS or Linux use `python3.12` and `.venv/bin/python`.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements\dev.txt
.\.venv\Scripts\python.exe setup_local.py        # creates .env and the local SQLite database
.\.venv\Scripts\python.exe manage.py seed_demo   # under a minute; prints the demo password
.\run_server.bat                                 # or: .\.venv\Scripts\python.exe manage.py runserver
```

Open **http://127.0.0.1:8000/** and sign in with the password that `seed_demo` printed. For a smaller dataset that seeds in seconds, use `seed_demo --size small`.

| Role | Username |
|---|---|
| Super admin (whole group) | `superadmin` |
| Branch admin | `admin.madhapur` |
| Principal | `principal.madhapur` |
| Teacher (class teacher of Class 10-A, teaches Mathematics) | `teacher.madhapur` |
| Accountant (fees for Madhapur) | `accountant.madhapur` |
| Student (in Class 10-A) | `student1.madhapur` |
| Parent (of `student1.madhapur`) | `parent1.madhapur` |
| Second branch | `admin.benz-circle`, `principal.benz-circle`, `teacher.benz-circle`, `accountant.benz-circle`, `student1.benz-circle`, `parent1.benz-circle` |

The demo school, *Greenfield Group of Schools*, is synthetic: 2 branches, 250 students and their parents, about three months of attendance, two terms of results, leave requests, announcements, and two terms of fee invoices with office and online payments (some overdue). Accounts use `example.invalid` email addresses. Seeding refuses to run outside development settings or on a database that already has data. To reset the demo password, run `manage.py changepassword superadmin`.

### With Docker and PostgreSQL

Install Docker Desktop, run `python setup_local.py` once to create `.env`, then:

```powershell
docker compose up --build -d
docker compose exec web python manage.py seed_demo
```

Compose runs the full stack: PostgreSQL, Redis, the web app (gunicorn and WhiteNoise) on http://127.0.0.1:8000/, a Celery worker and scheduler, and Mailpit, which catches every email EduNexa sends so you can read them at http://127.0.0.1:8025/. Without Docker, background jobs simply run inside the request and emails print in the terminal. Data lives in a Docker volume. `docker compose stop` stops it; removing the volume deletes the data.

## Tests and code quality

```powershell
.\.venv\Scripts\python.exe -m pytest                 # 2 concurrency tests skip on SQLite
.\.venv\Scripts\python.exe -m pytest --cov           # with a coverage report
.\.venv\Scripts\ruff.exe check . ; .\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\pre-commit.exe install               # run ruff and file checks before each commit
```

Run the full suite, including the concurrent-write tests, against a throwaway PostgreSQL:

```powershell
docker run -d --rm --name edunexa-test-pg -e POSTGRES_USER=edunexa -e POSTGRES_PASSWORD=test-only -e POSTGRES_DB=edunexa -p 127.0.0.1:55432:5432 postgres:17-alpine
$env:DATABASE_URL = "postgresql://edunexa:test-only@127.0.0.1:55432/edunexa?sslmode=disable"
.\.venv\Scripts\python.exe -m pytest
docker stop edunexa-test-pg
```

## Project structure

```text
apps/
  core/          base model, security headers, pagination, template tags, health check, shared API code
  organization/  school group and branches
  audit/         activity log: AuditEvent, audit(), events()
  accounts/      users and roles, sign-in and throttling, account management
  academics/     academic years, classrooms, subjects, teacher assignments
  students/      students, enrollments, admission, guardians (parents)
  communication/ announcements, notifications, email
  attendance/    daily registers, leave requests, absence alerts
  exams/         exams, marks, result workflow, results notifications
  reports/       dashboards and charts, student report, report-card PDF, performance, activity log
  demo/          seed_demo, demo mode: one-click logins and the nightly reset
                 each domain app: selectors, policies, services, web views, api/, tests/ with factories
config/          settings (base, dev, prod, test, build), URLs, API URLs, WSGI
deploy/          production: Compose with Caddy HTTPS, env example, backup and restore scripts
e2e/             browser tests, API checks, crawl, and the upgrade, migration and deploy rehearsals
templates/       layout, partials and shared components
static/          design tokens, CSS, JavaScript, SVG icons
docs/            design, architecture, permissions, data rules, deployment, decision records
```

## Start a real school (without demo data)

Use a separate, empty database. After `setup_local.py`, skip `seed_demo` and run `manage.py createsuperuser`, then sign in and set up, in this order:

1. **Academic setup → Organisation name**, then **Branch** for each campus.
2. **Academic year** with its start and end dates.
3. **People & access → Staff account:** branch admins, principals and teachers.
4. **Academic setup → Classroom:** branch, year, grade, section and class teacher.
5. **Subjects**, then **Assign subject teacher** for each class and subject.
6. **Students → Add student** creates the login, admission number and enrollment together.

Initial passwords must be shared privately, and everyone must change theirs at first sign-in. There is no public sign-up.

## Documentation

- [Design and roadmap](docs/DESIGN.md): the six phases EduNexa was built in.
- [Architecture](docs/ARCHITECTURE.md): how the code is organised and how a request flows.
- [REST API](docs/API.md): signing in, conventions, errors and every endpoint.
- [Permissions](docs/PERMISSIONS.md): the full role-by-action access matrix.
- [Data rules](docs/DATA_RULES.md): attendance, results, grading, fees, timetable, import and promotion rules.
- [Deployment](docs/DEPLOYMENT.md): a Linux server with Docker Compose and HTTPS, releases, backups and restores, the public demo.
- [Security](docs/SECURITY.md): what protects the data, and the pre-release review.
- [End-to-end checks](e2e/README.md): the browser tests and rehearsals, and how to run them.
- [Upgrading](docs/UPGRADING.md): moving data from the single-app version, tested.
- [Decision records](docs/adr/): why the main technical choices were made.
- [Backlog](docs/BACKLOG.md): known limitations and follow-ups, with the phase likely to take each on.

## Status

Phases 1 to 5 are complete: the foundation and rebrand, the REST API, background jobs with the parent portal, fees with online payments (test mode), and academic operations (grades and terms, a versioned grading scale, timetables, CSV import and year-end promotion). Next is a live demo. See the [roadmap](docs/DESIGN.md#14-roadmap).
