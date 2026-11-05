# 5. No Django admin site

**Status:** Accepted, November 2026 (Phase 1)

## Context

Django's admin is a quick way to edit any model. But EduNexa's important rules live in services. Saving marks requires a draft exam, a current version number, a classroom row lock and an audit event. Publishing requires a principal and a complete, submitted mark sheet.

## Decision

Do not enable `django.contrib.admin`. All changes go through the application's pages, and later the API, which call the services.

## Consequences

- No back door around the approval workflow, the concurrency checks or the activity log.
- Every administrative task needs a real screen. Data fixes that have no screen yet need a reviewed data migration, as [DATA_RULES.md](../DATA_RULES.md) already describes for historical enrollment corrections.
- If an admin site is added later for support staff, it should be read-only.
