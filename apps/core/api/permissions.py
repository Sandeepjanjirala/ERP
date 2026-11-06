"""API access checks. These are the API's version of the web app's login_required/role_required.

Three layers, the same as the web pages:
1. Here: is the caller signed in, past the forced password change, and in an allowed role?
2. Selectors: every queryset is limited to the caller's scope, so other records return 404.
3. Services: every write checks its policy again (can_mark, can_publish, ...) and raises 403.
"""

# DRF imports the default permission class while rest_framework.views is still loading, so this
# module must not import rest_framework.views (directly, or through .exceptions).
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission


class PasswordChangeRequired(PermissionDenied):
    default_detail = "Change your initial password first: POST /api/v1/me/password/."
    default_code = "password_change_required"


class IsSignedIn(BasePermission):
    """The default for every endpoint: a signed-in, active user who has set their own password.

    A view sets `allow_before_password_change = True` to stay reachable during the forced change
    (the profile, the password change itself, and sign-out).
    """

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.must_change_password and not getattr(view, "allow_before_password_change", False):
            raise PasswordChangeRequired
        return True


def role_in(*roles):
    """A permission class that also requires one of `roles`, like the web's @role_required."""

    class RoleIn(IsSignedIn):
        def has_permission(self, request, view):
            return super().has_permission(request, view) and request.user.role in roles

    RoleIn.__name__ = "RoleIn_" + "_".join(roles)
    return RoleIn
