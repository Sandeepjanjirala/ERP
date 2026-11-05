# 4. The product name is configuration; the school name is data

**Status:** Accepted, November 2026 (Phase 1)

## Context

Page titles and the sidebar showed the organisation name from the database, so the product had no fixed name. Demo data made pages read "Vidya Schools · Demo".

## Decision

- `settings.BRAND` holds the product identity (`EduNexa`, `School ERP`) and is the only place it is defined. A context processor passes it to templates. Emails, which render without a request, receive it through `extra_email_context`.
- Every title reads `<page> · EduNexa`.
- The school group's own name stays in the `Organization` record. It is shown only where it belongs: the workspace label in the sidebar and breadcrumb, and later report cards and receipts.

## Consequences

- One consistent name everywhere, which can be changed in one line.
- The same split is what multi-school hosting would need later: the product stays EduNexa and each customer's name is data.
- Tests check the title, the sign-in page and the password-reset email, so the rule can't drift.
