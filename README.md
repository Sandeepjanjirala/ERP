# EduNexa

**School ERP for school groups with many branches, built with Django.**

[![CI](https://github.com/Sandeepjanjirala/ERP/actions/workflows/ci.yml/badge.svg)](https://github.com/Sandeepjanjirala/ERP/actions/workflows/ci.yml)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue)
![Django 5.2 LTS](https://img.shields.io/badge/django-5.2%20LTS-0C4B33)
![PostgreSQL 17](https://img.shields.io/badge/postgresql-17-336791)

EduNexa runs the daily work of a school group: branches, classrooms and teachers, daily attendance, exams with a principal-approval workflow, student reports and performance analysis. Every role sees only what it is responsible for, and every important change is recorded in an activity log. Everything is also available through a documented REST API.

![Overview dashboard](docs/screenshots/dashboard.png)

| Exam review (principal) | Student report (dark theme) |
|---|---|
| ![Exam review](docs/screenshots/exam-review.png) | ![Student report in dark mode](docs/screenshots/student-report-dark.png) |

## What it does

- **Seven roles:** super admin, branch admin, principal, teacher, accountant, student and parent. Each sees only its own branch, classes, records or children; accountants see fees and nothing academic.
- **Daily attendance:** one register per class per day. Every student must be marked, corrections need a reason, and before/after values are logged.
- **Exams and results:** teachers enter marks, then the workflow runs Draft → Submitted → Published. Only principals publish, and reopening a published exam needs a reason.
- **Parents:** parent accounts linked to one or more children, with a primary contact. Parents follow attendance and results, download report cards, and apply for leave, which the class teacher approves.
- **Fees and payments:** fee plans per grade, invoices, concessions, cash/UPI/cheque at the office, and online payment through Razorpay (test mode) or a built-in Sandbox. Receipts are numbered without gaps and emailed as PDFs; overdue families get a weekly reminder; finance staff get a collection report with CSV. No real money moves.
- **Notifications:** a notification bell and email for absences, published results, leave decisions and announcements, sent in the background.
- **Dashboards:** for each role, with attendance charts, students below 75% attendance, and what is waiting for you.
- **Reports:** report-card PDFs, printable student reports, subject performance analysis, and CSV exports scoped to your access and protected against spreadsheet formula injection.
- **Security:** login throttling, a forced password change on first sign-in, a strict Content-Security-Policy, HSTS and secure cookies, and signed-in pages are never cached.
- **Interface:** light and dark themes, responsive down to phone width, and keyboard and screen-reader friendly.
- **REST API:** every feature under `/api/v1/` (password reset by email stays a web flow), with JWT sign-in, Swagger UI at `/api/docs/` and ReDoc at `/api/redoc/`. See [API.md](docs/API.md).

## Engineering highlights

| What | How |
|---|---|
| No lost updates | Registers and mark sheets carry a version number, and writes lock the classroom row. Two people saving at once gives one save and one "reload" message, tested with real threads on PostgreSQL. |
| Rules the database enforces | One register per class per day, scores never above the maximum, valid role/branch combinations: these are constraints in the database, not just form checks. |
| Business logic outside views | Each domain app has `selectors` (reads already limited to the user's scope), `policies` (who may do what) and `services` (writes with transactions, locks and audit). Views only parse input and render output. |
| One set of rules for web and API | The web pages and the REST API call the same selectors, policies and services, and every service checks its own policy, so the two can't disagree. See [ADR 0006](docs/adr/0006-rest-api.md). |
| Careful API security | 15-minute access tokens; refresh tokens that rotate and are blacklisted after use; a password change or deactivation revokes tokens; one sign-in limit shared with the web; out-of-scope records are 404. |
| Background jobs done properly | Celery and Redis. Jobs are queued only after the database commits, are safe to run twice (each notification has a unique key), and re-check the facts before acting. CI starts a real worker and checks it takes jobs. See [ADR 0007](docs/adr/0007-background-jobs-and-caching.md). |
| Payments done carefully | Money in integer paise. A payment is recorded only on a provider-signed webhook (HMAC, constant-time check) or a verified checkout whose amount is fetched from the provider. A repeated event records nothing; money beyond the balance is kept as excess, never discarded. Receipt numbers come from a locked counter inside the payment's transaction, so they are gapless. See [ADR 0008](docs/adr/0008-payments.md). |
| Caching that can't go stale | Dashboard numbers are cached in Redis under keys that include a fingerprint of the registers, so any change gives a new key. |
| No N+1 queries | A test measures each API list's SQL queries with few rows and with many; the count must not change. |
| Layered apps | Eleven apps ordered by dependency, with no circular imports. See [ARCHITECTURE.md](docs/ARCHITECTURE.md). |
| Production safety | Settings per environment. Production refuses to start without a secret key and PostgreSQL, and Django's `check --deploy` runs in CI. |
| Tested | 379 tests (plus 749 table-driven cases, such as every API endpoint for every role) with 95% branch coverage. CI runs them on PostgreSQL along with lint, a migration check, an OpenAPI schema check, a real Celery worker taking a job through Redis, and a Docker build. |

## Run it on your computer

You need **Python 3.12**. These commands are for Windows PowerShell; on macOS or Linux use `python3.12` and `.venv/bin/python`.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements\dev.txt
.\.venv\Scripts\python.exe setup_local.py        # creates .env and the local SQLite database
.\.venv\Scripts\python.exe manage.py seed_demo   # about a minute; prints the demo password
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
docker compose exec web python manage.py seed_demo   # a few minutes: Docker on Windows adds a little to every query
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
  demo/          seed_demo command
                 each domain app: selectors, policies, services, web views, api/, tests/ with factories
config/          settings (base, dev, prod, test), URLs, API URLs, WSGI
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

- [Design and roadmap](docs/DESIGN.md): where EduNexa is going, in six phases.
- [Architecture](docs/ARCHITECTURE.md): how the code is organised and how a request flows.
- [REST API](docs/API.md): signing in, conventions, errors and every endpoint.
- [Permissions](docs/PERMISSIONS.md): the full role-by-action access matrix.
- [Data rules](docs/DATA_RULES.md): attendance, results and fee rules.
- [Deployment](docs/DEPLOYMENT.md): production settings and release steps.
- [Upgrading](docs/UPGRADING.md): moving data from the single-app version, tested.
- [Decision records](docs/adr/): why the main technical choices were made.
- [Backlog](docs/BACKLOG.md): known limitations and follow-ups, with the phase likely to take each on.

## Status

Phases 1 to 4 are complete: the foundation and rebrand, the REST API, background jobs with the parent portal, and fees with online payments (test mode). Next are timetables and academic operations, then a live demo. See the [roadmap](docs/DESIGN.md#14-roadmap).
