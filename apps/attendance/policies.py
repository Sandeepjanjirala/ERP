"""Who may record daily attendance."""

from apps.accounts.models import User


def can_attend(user, classroom):
    return user.system_admin or (
        user.branch_id == classroom.branch_id
        and (
            user.role == User.Role.ADMIN
            or (user.role == User.Role.TEACHER and classroom.homeroom_teacher_id == user.pk)
        )
    )
