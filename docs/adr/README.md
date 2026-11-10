# Architecture decision records

Short notes on the main technical choices: the context, the decision, and what it costs. New decisions get the next number; old records are not edited, only superseded.

| No. | Decision | Status |
|---|---|---|
| [0001](0001-modular-monolith.md) | One Django project split into layered domain apps | Accepted |
| [0002](0002-services-selectors-policies.md) | Business logic in services, selectors and policies, not views | Accepted |
| [0003](0003-settings-per-environment.md) | One settings module per environment | Accepted |
| [0004](0004-brand-as-configuration.md) | The product name is configuration; the school name is data | Accepted |
| [0005](0005-no-django-admin.md) | No Django admin site | Accepted |
| [0006](0006-rest-api.md) | A REST API on the same services as the web app | Accepted |
| [0007](0007-background-jobs-and-caching.md) | Background jobs after commit, idempotent; cache keys that carry a data version | Accepted |
| [0008](0008-payments.md) | Payments: integer paise, signed webhooks, idempotent capture, gapless receipts | Accepted |
| [0009](0009-grades-and-terms.md) | Grades and terms as records; exams placed in terms by their date | Accepted |
| [0010](0010-versioned-grading-scale.md) | A versioned grading scale that never rewrites published results | Accepted |
| [0011](0011-timetable-and-htmx.md) | Timetable clashes stopped by the database; htmx without loosening the CSP | Accepted |
| [0012](0012-import-and-promotion.md) | Bulk changes: a dry-run preview, then all or nothing | Accepted |
| [0013](0013-leaving-and-access.md) | Leaving school: records kept, sign-in ended, a limited grace period | Accepted |
| [0014](0014-demo-mode.md) | Demo mode: a public showcase that can never touch real data | Accepted |
