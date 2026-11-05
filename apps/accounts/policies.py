"""Who may change which accounts."""

from .decorators import MANAGERS


def can_manage_account(actor, person):
    """Super admins manage every branch account; branch admins manage their teachers and students."""
    if actor.role not in MANAGERS or person.role == "superadmin":
        return False
    if actor.system_admin:
        return True
    return person.branch_id == actor.branch_id and person.role in ("teacher", "student")


def can_change_access(actor, person):
    """Deactivating or reactivating follows the same rule, but never for your own account."""
    return person.pk != actor.pk and can_manage_account(actor, person)
