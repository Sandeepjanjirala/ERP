# Backlog

Known limitations and follow-ups that were left out of a phase on purpose. Each item says where it came from and, where it fits, which phase is likely to take it on. When an item is done, remove it in the same commit.

## From Phase 4 (fees and payments)

| Item | Why it was left | Possible fix | Likely phase |
|---|---|---|---|
| Refunds are not recorded: excess and review payments are listed for finance staff to refund outside EduNexa | Out of scope for Phase 4, by decision | A refund model against a payment (with the provider's refund API for online payments), audited, reducing `excess` | Later |
| No late fees | Out of scope for Phase 4 | A late-fee rule per plan, added as an invoice line by the daily job, once per invoice | Later |
| No instalments: one invoice per plan and title | Out of scope for Phase 4; terms can be issued as separate invoices | Instalment schedules on a plan, issuing one invoice per instalment | Later |
| INR only | Out of scope for Phase 4; another currency is held for review, never counted | A currency per branch, with amounts stored in that currency's minor units | Later |
| Payments run in test mode only; the Sandbox stays enabled | Requirement: no real money and no production credentials | Before going live: live keys, a reviewed change to the `rzp_test_` guard, disable the Sandbox, legal and finance sign-off | Later |
| The Razorpay checkout page's Content-Security-Policy has not been checked live | No Razorpay test keys were used; the page was tested with HTTP mocked | Open the checkout with test keys and adjust the page's `csp_add` if the browser blocks anything | 6 |
| A fee plan uses the classroom's grade text | A Grade model arrives in Phase 5 | Migrate each plan to the Grade with the same branch and name, then drop the text (see [DATA_RULES.md](DATA_RULES.md#fees)) | 5 |
| Fee heads and plans can be read but not changed through the API | The web pages cover setup; the API covers daily work (invoices, payments, issuing) | Add create and update endpoints over `save_fee_head` and `save_fee_plan` | 5 or 6 |
| No collection report endpoint in the API | `/api/v1/payments/` with filters covers the data | Add `/api/v1/reports/collections/` with totals and CSV | 6 |
| Seeded payment dates are spread across the term by a direct update after the service records them | Services stamp the current time, which is right for real payments | Leave as is (demo only), or let the seed pass a clock | None planned |

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
| GitHub CI has not yet run Phases 2 to 4, including the new Redis worker step | Nothing is pushed until after Phase 6 | Push and watch CI | 6 |

## Carried over from Phases 1 and 2

| Item | Possible fix | Likely phase |
|---|---|---|
| The app layering rule (an app imports only from apps below it) is a convention, not a tool check | Add an import-linter contract to CI | 5 or 6 |
| Layouts were checked by screenshot, not on real phones | Test on a real Android and iOS device | 6 |
| Nothing has run on a real host with HTTPS yet | Deploy with managed PostgreSQL and Redis | 6 |
| ReDoc shows operation ids (such as `activity_list`) where a written summary would read better | Add short summaries with `extend_schema(summary=...)` | 6 |
| ReDoc's "API docs by Redocly" logo is blocked by the CSP (on purpose: no third-party requests) | Hide the badge with CSS, or leave as is | 6 |
| Upgrading a database made before Phase 1 is three manual commands | Documented in [UPGRADING.md](UPGRADING.md); only matters for pre-Phase-1 data | None planned |
