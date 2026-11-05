"""Who may create exams, enter marks and publish results."""

from apps.academics.models import TeachingAssignment
from apps.accounts.models import User

# Roles that may create exams (teachers only for their own class and subject).
EXAM_AUTHORS = (User.Role.SUPER, User.Role.ADMIN, User.Role.TEACHER)


def can_create_exam(user, classroom, subject):
    if user.system_admin:
        return True
    if user.branch_id != classroom.branch_id:
        return False
    if user.role == User.Role.ADMIN:
        return True
    return (
        user.role == User.Role.TEACHER
        and TeachingAssignment.objects.filter(
            teacher=user, classroom=classroom, subject=subject
        ).exists()
    )


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
