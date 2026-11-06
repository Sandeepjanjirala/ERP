"""Who may do what with fees."""

from apps.accounts.models import User


def _in_branch(user, branch):
    return user.system_admin or (branch is not None and branch.pk == user.branch_id)


def can_set_up_fees(user, branch):
    """Fee heads and plans, concessions and cancellations: super admins and branch admins."""
    return user.role in User.MANAGERS and _in_branch(user, branch)


def can_collect_fees(user, branch):
    """Issue invoices and record counter payments: admins and the branch's accountant."""
    return user.role in User.FINANCE and _in_branch(user, branch)


def can_pay_online(user, invoice):
    """A parent, for their own child's invoice."""
    return user.is_parent and invoice.student.guardian_links.filter(guardian__user=user).exists()
