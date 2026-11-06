"""Who may admit and enroll students."""


def can_enroll(actor, classroom):
    """Super admins anywhere; branch admins in their own branch."""
    return actor.is_manager and (actor.system_admin or classroom.branch_id == actor.branch_id)
