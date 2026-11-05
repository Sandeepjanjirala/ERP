"""Read queries for the activity log, already limited to what the user may see."""

from .models import AuditEvent


def events(user):
    """Everything for super admins; otherwise only the user's branch."""
    queryset = AuditEvent.objects.select_related("actor", "branch")
    if not user.system_admin:
        queryset = queryset.filter(branch=user.branch)
    return queryset
