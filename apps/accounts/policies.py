"""Who may change which accounts."""

from .models import User


def can_manage_account(actor, person):
    """Super admins manage every branch account; branch admins manage the rest of their branch:
    teachers, accountants, students and parents."""
    if not actor.is_manager or person.role == User.Role.SUPER:
        return False
    if actor.system_admin:
        return True
    return person.branch_id == actor.branch_id and person.role in (
        User.Role.TEACHER,
        User.Role.ACCOUNTANT,
        User.Role.STUDENT,
        User.Role.PARENT,
    )


def can_change_access(actor, person):
    """Deactivating or reactivating follows the same rule, but never for your own account."""
    return person.pk != actor.pk and can_manage_account(actor, person)


def staff_roles_for(actor):
    """Staff roles the actor may create accounts for. Students are added through admission."""
    if actor.system_admin:
        return (User.Role.ADMIN, User.Role.PRINCIPAL, User.Role.TEACHER, User.Role.ACCOUNTANT)
    if actor.role == User.Role.ADMIN:
        return (User.Role.TEACHER, User.Role.ACCOUNTANT)
    return ()
