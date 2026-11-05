"""Who may change which accounts."""

from .models import User


def can_manage_account(actor, person):
    """Super admins manage every branch account; branch admins manage their teachers and students."""
    if not actor.is_manager or person.role == User.Role.SUPER:
        return False
    if actor.system_admin:
        return True
    return person.branch_id == actor.branch_id and person.role in (
        User.Role.TEACHER,
        User.Role.STUDENT,
    )


def can_change_access(actor, person):
    """Deactivating or reactivating follows the same rule, but never for your own account."""
    return person.pk != actor.pk and can_manage_account(actor, person)
