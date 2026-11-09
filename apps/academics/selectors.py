"""Read queries for classrooms, subjects and teaching assignments, limited to what the user may see."""

from django.db.models import Q

from apps.accounts.models import User
from apps.organization.selectors import branches

from .models import Classroom, Grade, Period, Subject, TeachingAssignment, TimetableSlot


def classrooms(user):
    qs = Classroom.objects.filter(branch__in=branches(user)).select_related(
        "branch", "year", "grade", "homeroom_teacher"
    )
    if user.role == User.Role.TEACHER:
        qs = qs.filter(Q(homeroom_teacher=user) | Q(teaching__teacher=user)).distinct()
    elif user.role == User.Role.STUDENT:
        qs = qs.filter(enrollments__student__user=user).distinct()
    elif user.role == User.Role.PARENT:
        # students sits above academics, so its guardian links are named, not imported.
        qs = qs.filter(enrollments__student__guardian_links__guardian__user=user).distinct()
    return qs


def grades(user):
    """The grades of the user's branches, in teaching order."""
    return Grade.objects.filter(branch__in=branches(user)).select_related("branch")


def subjects(user):
    return Subject.objects.filter(branch__in=branches(user)).select_related("branch")


def assignments(user):
    return TeachingAssignment.objects.filter(classroom__in=classrooms(user)).select_related(
        "teacher", "classroom__branch", "classroom__year", "classroom__grade", "subject"
    )


def periods(user):
    """The periods (bell schedule) of the user's branches, in order."""
    return Period.objects.filter(branch__in=branches(user)).select_related("branch")


def timetable_grid(classroom):
    """A class's week: its branch's periods, the weekdays, and the lesson in each (day, period)."""
    lessons = TimetableSlot.objects.filter(classroom=classroom).select_related(
        "period", "subject", "teacher"
    )
    period_list = list(Period.objects.filter(branch_id=classroom.branch_id))
    cells = {(lesson.weekday, lesson.period_id): lesson for lesson in lessons}
    return {
        "periods": period_list,
        "days": TimetableSlot.Day.choices,
        "cells": cells,
        "rows": week_rows(period_list, cells),
    }


def week_rows(period_list, cells):
    """One row per period: the period and, for each weekday, (day, lesson or None)."""
    return [
        {
            "period": period,
            "cells": [(day, cells.get((day, period.pk))) for day in TimetableSlot.Day.values],
        }
        for period in period_list
    ]


def teacher_lessons(teacher, year=None):
    """Every lesson a teacher gives, for one year (default: all years), in weekly order."""
    lessons = TimetableSlot.objects.filter(teacher=teacher).select_related(
        "classroom__grade", "classroom__year", "period", "subject"
    )
    return lessons.filter(year=year) if year else lessons
