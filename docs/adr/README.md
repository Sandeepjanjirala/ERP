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
