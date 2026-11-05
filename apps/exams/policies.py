"""Who may create exams, enter marks and publish results."""

from apps.academics.models import TeachingAssignment
from apps.accounts.models import User

from .models import Exam

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


def exam_actions(user, exam):
    """What the user can do to this exam right now; the web buttons and the API flags."""
    writer, publisher = can_mark(user, exam), can_publish(user, exam)
    draft = exam.status == Exam.Status.DRAFT
    return {
        "can_edit_marks": writer and draft,
        "can_submit": writer and draft,
        "can_publish": publisher and exam.status == Exam.Status.SUBMITTED,
        "can_reopen": publisher and not draft,
    }
