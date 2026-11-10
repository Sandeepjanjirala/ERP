"""Who may change the academic setup."""

# Records that belong to the whole school group, not one branch: super admins only.
GROUP_LEVEL = ("organization", "branch", "year", "term")


def can_manage_setup(actor, kind, branch=None):
    """Group-level records: super admins. Classrooms, subjects, assignments: managers of `branch`."""
    if kind in GROUP_LEVEL:
        return actor.system_admin
    return actor.is_manager and (
        actor.system_admin or (branch is not None and branch.pk == actor.branch_id)
    )
