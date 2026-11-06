"""Read queries for accounts, already limited to what the user may see."""

from apps.organization.selectors import branches

from .models import User


def people(user):
    """Accounts listed on People & access: all for super admins, otherwise the user's branch.

    Usernames are unique, so ending the ordering with them keeps pages stable: two people with
    the same role and first name can't swap places between page loads.
    """
    accounts = User.objects.select_related("branch")
    if user.system_admin:
        return accounts.order_by("role", "first_name", "username")
    return accounts.filter(branch__in=branches(user)).order_by(
        "branch__name", "role", "first_name", "username"
    )


def teachers(user):
    """Active teachers in the user's branches: the choices for homeroom and subject teacher."""
    return User.objects.filter(branch__in=branches(user), role=User.Role.TEACHER, is_active=True)


def parents(user):
    """Active parent accounts in the user's branches: the choices when linking a guardian."""
    return User.objects.filter(branch__in=branches(user), role=User.Role.PARENT, is_active=True)


def branch_accounts(user):
    """Accounts that belong to one of the user's branches. Super admins have no branch."""
    return User.objects.filter(branch__in=branches(user))
