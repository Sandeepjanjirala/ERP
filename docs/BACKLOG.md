# Backlog

Known limitations and follow-ups that were left out of a phase on purpose. Each item says where it came from and, where it fits, which phase is likely to take it on. When an item is done, remove it in the same commit.

## From Phase 5 (academic operations)

| Item | Why it was left | Possible fix | Likely phase |
|---|---|---|---|
| Exams published before the first grading scale show no grade | By decision: they were published without grading rules, and published results never change afterwards ([ADR 0010](adr/0010-versioned-grading-scale.md)) | Reopen and republish an exam (audited) if the school wants it graded | None planned |
| No timetable substitutions or one-off changes (a teacher absent for a day) | Out of scope for Phase 5 | A substitution record per date and period, shown on "My day" | Later |
| The CSV import covers students and guardians only, not staff or marks | Out of scope for Phase 5 | The same check-then-confirm pattern for staff and mark sheets | Later |
| Students who leave keep an active account | Promotion closes their enrollment; deactivating logins is a separate decision | Offer "deactivate accounts of students who left" after a promotion | Later |
| A promotion can't be undone with one click | Rare, and undoing must not lose attendance or marks recorded since | A reviewed reverse operation (delete untouched new enrollments, reopen old ones) | Later |
| The import's check is as slow as the import (each row is saved, then undone) | Exactness over speed; fine at 500 rows | Profile if larger files are needed | Later |
| Ctrl+K global search (DESIGN.md) | Not part of the approved Phase 5 plan | Search students, staff and invoices from the top bar | 6 |

## From Phase 4 (fees and payments)

| Item | Why it was left | Possible fix | Likely phase |
|---|---|---|---|
| Refunds are not recorded: excess and review payments are listed for finance staff to refund outside EduNexa | Out of scope for Phase 4, by decision | A refund model against a payment (with the provider's refund API for online payments), audited, reducing `excess` | Later |
| No late fees | Out of scope for Phase 4 | A late-fee rule per plan, added as an invoice line by the daily job, once per invoice | Later |
| No instalments: one invoice per plan and title | Out of scope for Phase 4; terms can be issued as separate invoices | Instalment schedules on a plan, issuing one invoice per instalment | Later |
| INR only | Out of scope for Phase 4; another currency is held for review, never counted | A currency per branch, with amounts stored in that currency's minor units | Later |
| Payments run in test mode only; the Sandbox stays enabled | Requirement: no real money and no production credentials | Before going live: live keys, a reviewed change to the `rzp_test_` guard, disable the Sandbox, legal and finance sign-off | Later |
| The Razorpay checkout page's Content-Security-Policy has not been checked live | No Razorpay test keys were used; the page was tested with HTTP mocked | Open the checkout with test keys and adjust the page's `csp_add` if the browser blocks anything | 6 |
| No collection report endpoint in the API | `/api/v1/payments/` with filters covers the data | Add `/api/v1/reports/collections/` with totals and CSV | 6 |
| Seeded payment dates are spread across the term by a direct update after the service records them | Services stamp the current time, which is right for real payments | Leave as is (demo only), or let the seed pass a clock | None planned |

## From Phase 3 (background jobs and parent portal)

| Item | Why it was left | Possible fix | Likely phase |
|---|---|---|---|
| The notification bell still reloads the page | Phase 5 used htmx for attendance, timetables and list filters | Poll or refresh the bell's count with htmx | 6 |
| The report card PDF is drawn during the request, not in a background job | It takes milliseconds and the person is waiting; see [ADR 0007](adr/0007-background-jobs-and-caching.md) | Move to a job only if PDFs become slow or are emailed in bulk (receipts in Phase 4 are emailed from a job) | 4 if needed |
| A parent account belongs to one branch, so siblings in different branches need two accounts | Every scope rule is per branch; a cross-branch parent needs a reviewed design | Let a guardian's children span branches, with selectors scoped by child, not by account branch | Later |
| An absence corrected on a later day sends no correction | Phase 5 sends corrections for same-day changes only, matching the alerts | Send corrections for recent days too, if schools ask | Later |
| Names in cached dashboard lists can be up to an hour old (the numbers never are) | The cache key carries a register fingerprint, not a fingerprint of names | Add a version for student names to the key, or shorten the timeout | Later |
| The full demo seed takes about 4 minutes under Docker on Windows (about 1 minute without Docker) | Every row goes through the real services, and Docker Desktop adds latency to each query | Batch the history inside one register per day, or seed inside the container network only | 6 |
| Production needs `REDIS_URL`, `SITE_URL`, one worker and exactly one `beat` | New processes and settings from Phase 3; documented in [DEPLOYMENT.md](DEPLOYMENT.md) | Set them up and check with `manage.py check_jobs` when deploying | 6 |
| GitHub CI has not yet run Phases 2 to 5, including the new Redis worker step | Nothing is pushed until after Phase 6 | Push and watch CI | 6 |

## Carried over from Phases 1 and 2

| Item | Possible fix | Likely phase |
|---|---|---|
| Layouts were checked by screenshot, not on real phones | Test on a real Android and iOS device | 6 |
| Nothing has run on a real host with HTTPS yet | Deploy with managed PostgreSQL and Redis | 6 |
| ReDoc shows operation ids (such as `activity_list`) where a written summary would read better | Add short summaries with `extend_schema(summary=...)` | 6 |
| ReDoc's "API docs by Redocly" logo is blocked by the CSP (on purpose: no third-party requests) | Hide the badge with CSS, or leave as is | 6 |
| Upgrading a database made before Phase 1 is three manual commands | Documented in [UPGRADING.md](UPGRADING.md); only matters for pre-Phase-1 data | None planned |
