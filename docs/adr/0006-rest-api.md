# 6. A REST API on the same services as the web app

**Status:** Accepted, November 2026 (Phase 2)

## Context

Phase 2 adds a REST API for mobile apps and integrations, covering every feature the web app has. The web app's rules already lived mostly in services and policies ([ADR 0002](0002-services-selectors-policies.md)), but some were still in forms and views: who may create an exam, which staff roles an admin may create, the register's date rules, the setup permissions, the dashboard's numbers. An API that copied those rules would drift from the web app.

## Decision

**One set of rules.** Before adding endpoints, each rule that lived in a form or view moved into a policy, selector or service. The web forms now call those functions too. API views only parse input, call the same selector or service, and return JSON. Each service checks its own policy, so a caller that skips the web form, or forgets a check, is still refused.

**Django REST Framework**, with:

- **drf-spectacular** for the OpenAPI schema, Swagger UI and ReDoc. The UI files are served from our own static files (`drf-spectacular-sidecar`), so the strict Content-Security-Policy stays in place.
- **SimpleJWT** for tokens: 15-minute access tokens; refresh tokens that rotate and are blacklisted after use; a password-hash fingerprint in each token, so a password change revokes the older ones.
- **django-filter** for filters whose choices come from selectors, so a filter value outside your scope is rejected.

**Errors keep their meaning.** Services raise Django exceptions, as before. One exception handler maps them for the API: `ValidationError` → 400, the version `Conflict` → 409, `PermissionDenied` → 403, `Http404` → 404. Every error has the same JSON shape.

**Safe defaults.** Every endpoint requires sign-in and a completed first password change. Each viewset declares `queryset = Model.objects.none()` and returns its selector from `get_queryset()`, so a view that forgot to scope its query would return nothing rather than everything. Sorting works only on fields a view declares, and always ends with the primary key.

**JSON in production.** The browsable API is a development aid only.

## Consequences

- The web app and the API can't disagree about permissions or business rules, and a permission-matrix test pins down who may call what.
- Moving the rules into services made the web app safer too. For example, `create_account` now checks the account policy itself instead of relying on the form's role list.
- Serializers are deliberately thin, so some model validation errors reach the API as general messages in `detail` rather than per-field ones.
- The branches endpoint is served by the `academics` app: creating a branch writes the activity log, and `organization` sits below `audit` in the layer order ([ADR 0001](0001-modular-monolith.md)).
- Password reset by email stays a web flow, because the link in the email opens a web page.
