"""Who may record daily attendance."""


def can_attend(user, classroom):
    return user.system_admin or (
        user.branch_id == classroom.branch_id
        and (
            user.role == "admin"
            or (user.role == "teacher" and classroom.homeroom_teacher_id == user.pk)
        )
    )
