from django.core.exceptions import ValidationError


class Conflict(ValidationError):
    """Someone else saved the same record first: its version number has moved on."""


def error_text(exc, duplicate_message):
    """A user-facing message for a failed save: validation messages, or the duplicate message."""
    return "; ".join(exc.messages) if isinstance(exc, ValidationError) else duplicate_message
