# Security

How EduNexa protects a school's data, and the review done before the first release (Phase 6, November 2026). To report a vulnerability, contact the maintainer privately instead of opening a public issue.

## What protects the data

- **Every page and endpoint needs sign-in**, except the sign-in page, the password-reset flow, `/health/` and the API documentation. A test opens every URL anonymously to keep it that way (`apps/core/tests/test_public_surface.py`).
- **Every query is scoped to the person asking.** Selectors filter by branch, class or child, and policies decide every action. The same rules serve the web pages and the API. Every role is tested against every API endpoint (`test_api_permissions.py`), and parents and accountants have their own scope tests ([PERMISSIONS.md](PERMISSIONS.md)).
- **Accounts:**
  - only administrators create them, and the first password must be changed;
  - sign-in and password-reset attempts are limited per account;
  - API tokens are short-lived, with rotating refresh tokens;
  - changing a password revokes every token;
  - switching an account off (by an administrator, or after leaving school) deletes its sessions and blacklists its tokens ([ADR 0013](adr/0013-leaving-and-access.md)).
- **The browser:**
  - HTTPS only, with HSTS;
  - a strict Content-Security-Policy: scripts and styles only from EduNexa's own files, with no inline code (the two third-party API-docs pages may use inline styles);
  - no framing, no content sniffing;
  - Secure, HttpOnly, SameSite cookies;
  - signed-in pages are never cached;
  - CSRF protection on every form, including htmx requests.
- **Data handling:**
  - money is in integer paise;
  - CSV exports neutralise spreadsheet formulas;
  - uploads are limited to 2 MB and checked in full before anything is saved;
  - every important change is in the activity log, with the request id.
- **Payments:** test mode only. Webhooks must carry a valid signature, and capture is idempotent ([ADR 0008](adr/0008-payments.md)).
- **Deployment ([DEPLOYMENT.md](DEPLOYMENT.md)):**
  - only Caddy is reachable from outside;
  - secrets live in `deploy/.env` (mode 600), never in Git or the image;
  - production refuses to start with incomplete or inconsistent settings;
  - the container runs as a non-root user;
  - backups are verified when written, and restores are rehearsed.
- **Dependencies:** pinned versions, scanned by `pip-audit` in CI.

## Phase 6 review

Areas reviewed:

- every URL as an anonymous visitor;
- the sign-in, password-reset and token flows;
- deactivation;
- the records download;
- uploads and exports;
- the demo mode's powers;
- the CSP on every page for every role (a real-browser crawl, `e2e/crawl.py`);
- the production settings and `check --deploy`;
- HTTPS and headers on the rehearsed stack;
- the Docker image contents;
- backups;
- known vulnerabilities in dependencies.

### Fixed

| Finding | Severity | Fix |
|---|---|---|
| Students and parents who left kept working accounts indefinitely | High | Nightly access review with a limited grace period; records kept (00d9ec2) |
| Switching an account off left its live sessions and API refresh tokens usable after it was switched back on | Medium | Sessions deleted and refresh tokens blacklisted whenever an account is switched off (00d9ec2) |
| On a server, `deploy/.env` (all secrets) and `deploy/backups/` (personal data) would have been copied into the Docker image | High | Excluded by `.dockerignore`, and backups by `.gitignore`; checked by building an image (ab03539) |
| Production could start with an `http://` site address, mismatched host or CSRF settings, or no Redis or email | Medium | Production refuses to start, naming the setting (8843563) |
| Sign-in attempt counters were never deleted, so attempts on made-up usernames grew a table without limit | Low | Cleared nightly a day after their window (734a926) |
| Inline styles were allowed on every page | Low | Removed from the app's pages (a `<meter>` replaces a styled bar); allowed only on the two API-docs pages |

### Accepted, or open

| Item | Severity | Why / what to do |
|---|---|---|
| Sign-in and reset limits are per account, not per IP address (the API also limits anonymous requests to 60 a minute per address) | Medium | Add rate limiting at the host or a CDN before a public launch; Caddy's standard image has none |
| PostgreSQL and Redis traffic is not encrypted inside the Docker network | Low | Single host, not reachable from outside. Use TLS if they move to separate machines |
| The activity log can't be edited in the app, but database operators can change it | Low | Documented; restrict database access to operators |
| The API documentation is public (endpoints and fields, never data) | Info | A deliberate choice, like most API references |
| The Razorpay checkout page's CSP hasn't been checked with live test keys | Low | Check before enabling Razorpay ([backlog](BACKLOG.md)) |
| Demo visitors can change the demo's data until the nightly reset | Info | By design; the reset refuses any non-demo database ([ADR 0014](adr/0014-demo-mode.md)) |
