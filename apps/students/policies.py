"""Who may admit and enroll students."""


def can_enroll(actor, classroom):
    """Super admins anywhere; branch admins in their own branch."""
    return actor.is_manager and (actor.system_admin or classroom.branch_id == actor.branch_id)


def can_import(actor, branch):
    """Importing students from a CSV: super admins, and branch admins for their own branch."""
    return actor.is_manager and (actor.system_admin or branch.pk == actor.branch_id)


def can_manage_guardians(actor, student, parent):
    """Managers of the student's branch link parent accounts of that branch."""
    return (
        actor.is_manager
        and (actor.system_admin or student.user.branch_id == actor.branch_id)
        and parent.is_parent
        and parent.branch_id == student.user.branch_id
    )
