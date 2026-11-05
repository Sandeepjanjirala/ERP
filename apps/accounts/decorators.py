from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

MANAGERS = ("superadmin", "admin")


LEADERS = ("superadmin", "admin", "principal")


def role_required(*allowed):
    """View decorator: sign-in required, and the user's role must be one of `allowed` (else 403)."""

    def decorator(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.user.role not in allowed:
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
