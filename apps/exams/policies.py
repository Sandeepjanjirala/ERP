"""Who may enter marks and who may publish results."""

from apps.academics.models import TeachingAssignment
from apps.accounts.models import User


def can_mark(user, exam):
    return user.system_admin or (
        user.role == User.Role.TEACHER
        and user.branch_id == exam.classroom.branch_id
        and TeachingAssignment.objects.filter(
            teacher=user, classroom=exam.classroom, subject=exam.subject
        ).exists()
    )


def can_publish(user, exam):
    return user.system_admin or (
        user.role == User.Role.PRINCIPAL and user.branch_id == exam.classroom.branch_id
    )
