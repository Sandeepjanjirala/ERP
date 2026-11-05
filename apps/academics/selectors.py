"""Read queries for classrooms, subjects and teaching assignments, limited to what the user may see."""

from django.db.models import Q

from apps.accounts.models import User
from apps.organization.selectors import branches

from .models import Classroom, Subject, TeachingAssignment


def classrooms(user):
    qs = Classroom.objects.filter(branch__in=branches(user)).select_related(
        "branch", "year", "homeroom_teacher"
    )
    if user.role == User.Role.TEACHER:
        qs = qs.filter(Q(homeroom_teacher=user) | Q(teaching__teacher=user)).distinct()
    elif user.role == User.Role.STUDENT:
        qs = qs.filter(enrollments__student__user=user).distinct()
    return qs


def subjects(user):
    return Subject.objects.filter(branch__in=branches(user)).select_related("branch")


def assignments(user):
    return TeachingAssignment.objects.filter(classroom__in=classrooms(user)).select_related(
        "teacher", "classroom__branch", "classroom__year", "subject"
    )
