# 2. Business logic in services, selectors and policies, not views

**Status:** Accepted, November 2026 (Phase 1)

## Context

Some writes, such as creating accounts and saving setup records, were coded directly in views, next to request parsing and template rendering. Phase 2 adds a REST API. If the rules live in views, the API would have to copy them, and the two copies would drift apart.

## Decision

Each domain app separates three kinds of code:

- **Selectors** (`selectors.py`) are reads, already limited to what the user may see. For example, `exams(user)` returns only a teacher's assigned class and subject.
- **Policies** (`policies.py`) are yes/no permission checks, such as `can_publish(user, exam)`.
- **Services** (`services.py`) are every write. Each one opens a transaction, locks rows when needed, re-checks the policy, checks version numbers, and records an audit event.

Views (and later API views) only parse input, call a selector or service, and render a response.

## Consequences

- The web pages and the coming API share exactly the same rules.
- A forgotten permission check in a view is still caught by the service, which re-checks the policy.
- Services can be tested directly, without HTTP. For example, `toggle_access(admin, principal)` must raise `PermissionDenied`.
- There are more files per app, and simple pages still go through a service call.
