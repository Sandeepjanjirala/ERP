"""Read queries for accounts, already limited to what the user may see."""

from apps.organization.selectors import branches

from .models import User


def people(user):
    """Accounts listed on People & access: all for super admins, otherwise the user's branch."""
    if user.system_admin:
        return User.objects.order_by("role", "first_name")
    return User.objects.filter(branch__in=branches(user)).order_by(
        "branch__name", "role", "first_name"
    )


def branch_accounts(user):
    """Accounts that belong to one of the user's branches. Super admins have no branch."""
    return User.objects.filter(branch__in=branches(user))
