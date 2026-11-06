"""One error shape for the whole API, and Django's exceptions mapped to HTTP status codes.

Services raise plain Django exceptions so the web pages and the API can share them. This handler
turns them into API responses:

    ValidationError       -> 400  {"code": "invalid", "detail": "...", "fields": {...}}
    Conflict (stale data) -> 409  {"code": "conflict", "detail": "..."}
    IntegrityError        -> 409  (a duplicate that slipped past validation, e.g. in a race)
    PermissionDenied      -> 403  {"code": "permission_denied", "detail": "..."}
    Http404               -> 404  {"code": "not_found", "detail": "..."}
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework import exceptions, status
from rest_framework.serializers import as_serializer_error
from rest_framework.views import exception_handler as drf_exception_handler

from apps.core.exceptions import Conflict


class StaleVersion(exceptions.APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This record changed since you loaded it. Reload and try again."
    default_code = "conflict"


def first_message(errors):
    """The first message in a nested DRF error structure, for the top-level `detail`."""
    while isinstance(errors, dict | list) and errors:
        errors = next(iter(errors.values())) if isinstance(errors, dict) else errors[0]
    return str(errors) if errors else "Check the highlighted fields."


def exception_handler(exc, context):
    if isinstance(exc, Conflict):
        exc = StaleVersion("; ".join(exc.messages))
    elif isinstance(exc, DjangoValidationError):
        exc = exceptions.ValidationError(as_serializer_error(exc))
    elif isinstance(exc, IntegrityError):
        exc = StaleVersion("This record already exists or was changed by someone else.")

    response = drf_exception_handler(exc, context)
    if response is None:
        return None
    if isinstance(exc, exceptions.ValidationError):
        fields = response.data if isinstance(response.data, dict) else {}
        general = fields.pop("non_field_errors", None) or (
            response.data if isinstance(response.data, list) else None
        )
        response.data = {
            "code": "invalid",
            "detail": first_message(general or fields),
            "fields": fields,
        }
    else:
        data = response.data if isinstance(response.data, dict) else {"detail": response.data}
        detail = data.get("detail", "")
        response.data = {
            "code": str(data.get("code") or getattr(detail, "code", None) or exc.default_code),
            "detail": str(detail),
        }
    return response
