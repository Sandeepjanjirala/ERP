"""Read queries for accounts, already limited to what the user may see."""

from apps.organization.selectors import branches

from .models import User


def people(user):
    """Accounts listed on People & access: all for super admins, otherwise the user's branch.

    Usernames are unique, so ending the ordering with them keeps pages stable: two people with
    the same role and first name can't swap places between page loads.
    """
    if user.system_admin:
        return User.objects.order_by("role", "first_name", "username")
    return User.objects.filter(branch__in=branches(user)).order_by(
        "branch__name", "role", "first_name", "username"
    )


def branch_accounts(user):
    """Accounts that belong to one of the user's branches. Super admins have no branch."""
    return User.objects.filter(branch__in=branches(user))
