# 13. Leaving school: records kept, sign-in ended, a limited grace period

**Status:** Accepted, November 2026 (Phase 6)

## Context

Students leave mid-year and at year end. Their records (marks, attendance, fees, receipts) must be kept, but an account that never ends is a standing risk: a former student or parent can keep reading data, and an old phone keeps a signed-in session or API token. A family still needs time to download records and pay what is owed.

## Decision

**Leaving is a date, not a deletion.** An admin records the last day at school (`record_leaving`: a reason is required, the day must fall in the year and not before recorded attendance). It is audited. Nothing is deleted.

**A nightly review switches accounts off and back on** (`review_access`, the `review-account-access` beat job at 02:30):

- A student's sign-in stops the day after their last enrollment ends, and comes back if they are enrolled again.
- A parent keeps access while any child is enrolled. After the last child leaves they keep it for `LEAVER_GRACE_DAYS` (30 by default), or `LEAVER_FEES_GRACE_DAYS` (90) while an invoice is unpaid. This is never indefinite: after that, fees are paid at the school office.
- The parent is emailed the end date once, with a link to the records and, if fees are owed, to pay online. A banner shows the date on every page.
- An end date a parent has been told is never brought forward.
- The review records why it switched an account off (`deactivated_reason`), so it switches back on only accounts it switched off itself. An administrator who switches a leaver back on gives them a fresh grace period.

**Switching off revokes access**, whether the review or an administrator does it. Live web sessions are deleted, and every outstanding API refresh token is blacklisted. So switching the account back on later never revives an old session or token.

**Records go home as one ZIP** (`/students/<id>/records.zip`):

- a report card for every year enrolled;
- for parents and finance staff, the fee statement and every receipt.

It is built from what the person downloading may see, and audited. After access ends, the office downloads the same pack for the family.

## Consequences

- No data is lost, and access ends on a predictable, announced date without manual work.
- Revocation is immediate on the server. An access token already issued stays valid until it expires (at most 15 minutes), and Django and the API also refuse a switched-off account on every request.
- The review runs one query per parent with children, which is fine for a school's numbers.
