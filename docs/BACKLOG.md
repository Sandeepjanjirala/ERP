# Backlog

Known limitations and follow-ups that were left out of a phase on purpose. Each item says where it came from and, where it fits, which phase is likely to take it on. When an item is done, remove it in the same commit.

## From Phase 3 (background jobs and parent portal)

| Item | Why it was left | Possible fix | Likely phase |
|---|---|---|---|
| HTMX is not used yet: the notification bell, filters and forms reload the page | Server-rendered pages were enough for the Phase 3 features | Add vendored HTMX for the bell, one-tap attendance and live filters, keeping the CSP strict (no `hx-on`, no eval) | 5 |
| The report card PDF is drawn during the request, not in a background job | It takes milliseconds and the person is waiting; see [ADR 0007](adr/0007-background-jobs-and-caching.md) | Move to a job only if PDFs become slow or are emailed in bulk (receipts in Phase 4 are emailed from a job) | 4 if needed |
| A parent account belongs to one branch, so siblings in different branches need two accounts | Every scope rule is per branch; a cross-branch parent needs a reviewed design | Let a guardian's children span branches, with selectors scoped by child, not by account branch | Later |
| An absence alert is not withdrawn when the register is later corrected to present | Alerts are only sent for today's register and re-check before sending; a later correction is rare | Send a short "correction" notification when an alerted absence is corrected the same day | 5 |
| Names in cached dashboard lists can be up to an hour old (the numbers never are) | The cache key carries a register fingerprint, not a fingerprint of names | Add a version for student names to the key, or shorten the timeout | Later |
| Charts keep their colours until the page reloads after a light/dark switch | Chart colours are read once from the design tokens | Redraw charts when the theme toggle fires | 5 |
| The full demo seed takes about 4 minutes under Docker on Windows (about 1 minute without Docker) | Every row goes through the real services, and Docker Desktop adds latency to each query | Batch the history inside one register per day, or seed inside the container network only | 6 |
| Production needs `REDIS_URL`, `SITE_URL`, one worker and exactly one `beat` | New processes and settings from Phase 3; documented in [DEPLOYMENT.md](DEPLOYMENT.md) | Set them up and check with `manage.py check_jobs` when deploying | 6 |
| GitHub CI has not yet run Phases 2 and 3, including the new Redis worker step | Nothing is pushed until after Phase 6 | Push and watch CI | 6 |

## Carried over from Phases 1 and 2

| Item | Possible fix | Likely phase |
|---|---|---|
| The app layering rule (an app imports only from apps below it) is a convention, not a tool check | Add an import-linter contract to CI | 5 or 6 |
| Layouts were checked by screenshot, not on real phones | Test on a real Android and iOS device | 6 |
| Nothing has run on a real host with HTTPS yet | Deploy with managed PostgreSQL and Redis | 6 |
| ReDoc shows operation ids (such as `activity_list`) where a written summary would read better | Add short summaries with `extend_schema(summary=...)` | 6 |
| ReDoc's "API docs by Redocly" logo is blocked by the CSP (on purpose: no third-party requests) | Hide the badge with CSS, or leave as is | 6 |
| Upgrading a database made before Phase 1 is three manual commands | Documented in [UPGRADING.md](UPGRADING.md); only matters for pre-Phase-1 data | None planned |
