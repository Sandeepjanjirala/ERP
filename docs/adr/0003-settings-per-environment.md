# 3. One settings module per environment

**Status:** Accepted, November 2026 (Phase 1)

## Context

A single settings file switched behaviour on a `DEBUG` environment variable. A missing or odd value could quietly change how the app ran. An earlier fix in the `.env` reader guarded against IDEs setting `DEBUG` to non-boolean values.

## Decision

Split the settings into `config/settings/`:

- **`base.py`** holds the shared settings and is secure by default: HTTPS-only cookies, SSL redirect, HSTS.
- **`dev.py`** turns on debug pages, uses SQLite unless `DATABASE_URL` is set, prints email to the console, and allows plain HTTP on localhost.
- **`prod.py`** refuses to start without `DJANGO_SECRET_KEY` and a PostgreSQL `DATABASE_URL`.
- **`test.py`** uses fast password hashing and in-memory email, and needs no `.env`.

`manage.py` defaults to dev, the WSGI server and the Docker image to prod, and pytest always uses test (`--ds` in `pyproject.toml`). `DEBUG` is no longer read from the environment.

## Consequences

- Production can't start with development defaults by accident. Tests prove the missing-secret and missing-database failures, and that `check --deploy` passes.
- Running `manage.py` on a server needs `DJANGO_SETTINGS_MODULE=config.settings.prod`. The Docker image sets this, and [DEPLOYMENT.md](../DEPLOYMENT.md) says so for other hosts.
