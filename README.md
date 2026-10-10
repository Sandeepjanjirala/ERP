# Vidya School Management

A Django application for **one organisation with multiple branches**, a small staff/student pilot, and **one attendance register per classroom per day**.

This is the school management application. The earlier school marketing website is a separate demonstration and does not contain these accounts or records.

## Start here on Windows

Install Python **3.12** first (the version used to verify this package). Extract this ZIP, open the `vidya_school` folder in PowerShell, and run:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe setup_local.py
.\.venv\Scripts\python.exe manage.py seed_demo
.\.venv\Scripts\python.exe manage.py runserver
```

Open **http://127.0.0.1:8000/**. Keep the terminal open while using it. Press Ctrl+C to stop.

`seed_demo` prints a **random demo password**. Use it with the usernames below. It runs only on an empty development database and will not overwrite existing users.

| Role | Demo username |
|---|---|
| Super admin | `superadmin` |
| Madhapur branch admin | `admin.madhapur` |
| Madhapur principal | `principal.madhapur` |
| Mathematics teacher / class teacher | `teacher.madhapur` |
| Science teacher | `mentor.madhapur` |
| Student | `student1.madhapur` |
| Second branch admin | `admin.benz-circle` |
| Second branch principal | `principal.benz-circle` |
| Second branch teacher | `teacher.benz-circle` |
| Second branch student | `student1.benz-circle` |

The 12 student records, marks, names, and attendance are **synthetic**. Demo accounts use `example.invalid` emails and cannot receive email. Demo seeding is blocked when `DEBUG=0`. Normal accounts created in the application must change their initial password on first login.

The simple local commands use SQLite, so you can inspect the application without installing a database. Use **PostgreSQL** for the staff/student pilot.

If you forget the generated demo password:

```powershell
.\.venv\Scripts\python.exe manage.py changepassword superadmin
```

## Start a clean pilot instead of demo data

Use a separate, empty database; do not put real student data into a demo installation. After `setup_local.py`, skip `seed_demo` and run:

```powershell
.\.venv\Scripts\python.exe manage.py createsuperuser
```

Sign in and configure these in order:

1. **Academic setup → Organisation name**.
2. **Add branch** for each campus.
3. **Add academic year**, with start and end dates.
4. **People & access → Staff account**: create branch admins, principals, and teachers.
5. **Academic setup → Classroom**: select its branch, year, grade, section, and daily attendance teacher.
6. Add branch subjects, then **Assign subject teacher** for each classroom/subject pair.
7. **Students → Add student** creates the student login, admission number, and enrollment together.
8. Teachers record attendance and create exams. The principal approves submitted results.

Student emails must be unique. There is no public self-registration. Share each initial password privately. Students do not need a ChatGPT account to use this Django application.

## Included workflows

- Separate super-admin, branch-admin, principal, teacher, and student accounts.
- Server-side role checks and branch/class/subject restrictions.
- Hashed passwords, login throttling, password changes, password reset, and account deactivation.
- Branches, academic years, classrooms, subjects, teaching assignments, and yearly student enrollments.
- Daily attendance with present, absent, late, and excused statuses.
- Correction reasons, versions to reject stale edits, and an activity log.
- Exams with configurable maximum and pass marks.
- Draft marks → teacher submission → principal publication.
- Locked submitted/published marks; principal reopening for corrections.
- Student-only published report cards, printable through the browser’s Print / Save PDF function.
- Subject and branch analysis, attendance summaries, and scoped CSV exports.
- Staff contact-detail editing and class/subject teacher reassignment.
- Synthetic demo data, database migrations, Docker configuration, and tests.

See [docs/PERMISSIONS.md](docs/PERMISSIONS.md) for the exact access matrix and [docs/DATA_RULES.md](docs/DATA_RULES.md) for calculation rules.

## Run with Docker and PostgreSQL

Install and start Docker Desktop. From the project folder, generate local settings if needed with `python setup_local.py` after installing requirements. Alternatively, copy `.env.example` to `.env` and supply fresh random `DJANGO_SECRET_KEY` and `POSTGRES_PASSWORD` values.

```powershell
docker compose up --build -d
docker compose exec web python manage.py createsuperuser
```

Open http://127.0.0.1:8000/. The compose file is for **local development**: the web port binds only to localhost, and PostgreSQL is accessible only inside the compose network. It uses a persistent database volume. It runs migrations for this single local web service. Do not run destructive volume-removal commands if you want to keep your records.

For synthetic Docker data, run `docker compose exec web python manage.py seed_demo` before creating any users. The Python-local SQLite database and Docker PostgreSQL database are separate.

Inspect logs or stop services:

```powershell
docker compose logs web
docker compose stop
```

## Automated checks

The test settings deliberately use a fast test-only password hasher and a simple static-file backend. Runtime settings retain Django’s normal password hashing and production static-file handling.

```powershell
.\.venv\Scripts\python.exe manage.py test --settings=school.test_settings --noinput
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py collectstatic --noinput
```

PostgreSQL, including concurrent-write tests:

```powershell
docker compose exec web python manage.py test --settings=school.test_settings --noinput
```

`.github/workflows/tests.yml` runs these tests with a PostgreSQL service after you push the extracted project to a GitHub repository with Actions enabled. This workflow is provided but has not been run against your repository.

See [docs/VERIFICATION.md](docs/VERIFICATION.md) for the checks actually completed in the build environment.

## Online deployment

The Django application is **not online yet**. The earlier ChatGPT Site URL serves the earlier marketing demo. A Django-capable host and PostgreSQL database are needed for this application.

Follow [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). Production refuses to start without `DJANGO_SECRET_KEY` and a PostgreSQL `DATABASE_URL`. Configure a real hostname, HTTPS, email delivery, and database backups before admitting real pilot users.

## Project structure

```text
config/          Runtime settings, URL routes, WSGI entry point
school/models.py Database models and validation
school/permissions.py  Role and object-scope rules
school/services.py     Transactional attendance and mark workflows
school/forms.py        Validated and scoped forms
school/views.py        Request handling, authentication and reports
school/migrations/     Committed database schema
school/tests.py        Access, workflow and concurrency tests
templates/       Server-rendered pages and authentication screens
static/school/   CSS and small progressive-enhancement JavaScript
docs/            Permissions, calculations, deployment and verification
```

## Current boundaries

This first version is a single-organisation application. A user has one role and one branch, except the organisation-level super admin. Teachers can have several subject/class assignments inside their branch.

Fees, parent accounts, timetable scheduling, transport, SMS, bulk student imports, AI predictions, multi-role users, and branch transfers are not implemented. There is no arbitrary role editor or public API. Daily attendance is classroom-level, not period-level. Existing enrollment departure dates and historical roster corrections currently require a supervised Django data migration; deactivating an account changes login access, not historical enrollment.

Data is not deleted through the UI. Result corrections require principal reopening and are audited. The audit log is application-managed history; a database operator could still modify database records.
