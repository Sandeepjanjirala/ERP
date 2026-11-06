"""Read queries for students and enrollments, already limited to what the user may see."""

from django.db.models import Q

from apps.academics.selectors import classrooms
from apps.accounts.models import User
from apps.organization.selectors import branches

from .models import Enrollment, Student, StudentGuardian


def students(user):
    qs = Student.objects.filter(user__branch__in=branches(user)).select_related(
        "user", "user__branch"
    )
    if user.role == User.Role.STUDENT:
        return qs.filter(user=user)
    if user.role == User.Role.PARENT:
        return qs.filter(guardian_links__guardian__user=user)
    if user.role == User.Role.TEACHER:
        return qs.filter(enrollments__classroom__in=classrooms(user)).distinct()
    return qs


def enrollments(user):
    qs = Enrollment.objects.filter(classroom__in=classrooms(user)).select_related(
        "student__user", "classroom__branch", "classroom__year", "year"
    )
    if user.role == User.Role.STUDENT:
        qs = qs.filter(student__user=user)
    elif user.role == User.Role.PARENT:
        # Their children only, not the children's classmates.
        qs = qs.filter(student__guardian_links__guardian__user=user)
    return qs


def guardian_links(user):
    """Student–guardian links the user may see: those of the students they may see."""
    return StudentGuardian.objects.filter(student__in=students(user)).select_related(
        "student__user", "guardian__user"
    )


def roster(classroom, day):
    return (
        classroom.enrollments.filter(joined_on__lte=day)
        .filter(Q(left_on__isnull=True) | Q(left_on__gte=day))
        .select_related("student__user")
    )
