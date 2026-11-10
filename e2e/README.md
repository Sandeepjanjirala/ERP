# End-to-end and integration checks

The unit and integration tests live in each app's `tests/` folder. This folder holds the checks that
exercise EduNexa as a whole: in a real browser, over real HTTP, and across database upgrades. CI
runs all of them (`.github/workflows/ci.yml`).

| Check | What it proves | How to run |
|---|---|---|
| `browser/` | Real Chromium (Playwright) against a live server with the real Content-Security-Policy: one-tap attendance, timetable editing, live filters, the notification bell and Ctrl+K search with htmx, confirmation dialogs, charts that follow the theme, keyboard use, the phone layout. Any console error or CSP violation fails the test. | `python -m playwright install chromium`, then `pytest e2e/browser` |
| `crawl.py` | Signs in as every role and opens every page they can reach (the sidebar, then a record from each list) in Chromium: any console error, failed page or CSP violation fails. | `python e2e/crawl.py <base URL> <demo password>`; also part of `rehearse_deploy.py` |
| `api_checks.py` | 69 checks over real HTTP with real tokens on a running stack: every role, every phase's workflows, background jobs and the emails they send. | Start the Docker Compose stack, `manage.py seed_demo --size small` inside it, then `python e2e/api_checks.py http://127.0.0.1:8000 <demo password>` |
| `walkthrough.py` | 154 checks through Django's full request stack on data upgraded from the single-app version: every page for every role, then every workflow of Phases 1 to 5. | Run by `rehearse_upgrade.py --walkthrough` |
| `rehearse_upgrade.py` | The upgrade from the single-app version works end to end (docs/UPGRADING.md): the old code's data, exported, converted and loaded. | `python e2e/rehearse_upgrade.py --database-url postgresql://.../empty --walkthrough` |
| `rehearse_migrations.py` | Every migration since a release keeps every row: build a database with an older release (or copy a real one), migrate it, compare every table. | `python e2e/rehearse_migrations.py build --from v0.1.0 --database-url postgresql://.../empty` or `check --database-url <a copy>` |
| `rehearse_deploy.py` | The production stack in `deploy/` works: built and started under production settings with Caddy's HTTPS, the deployment checklist, HTTP→HTTPS, certificate and security headers, secure cookies, the 69 API checks over HTTPS, the crawl for every role, and the backup and restore drill (every table compared with the backup). | `python e2e/rehearse_deploy.py` (Docker, ports 80 and 443 free; `--keep` leaves it running at https://edunexa.localhost) |
| `db_snapshot.py`, `db_compare.py` | The row snapshots the rehearsals compare. | Used by the rehearsals |

All of them change data: point them at throwaway databases, never at a real school's.
