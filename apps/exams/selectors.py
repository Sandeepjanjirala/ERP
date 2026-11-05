"""Read queries and summaries for exams and marks."""

from decimal import Decimal

from django.db.models import Q

from apps.academics.models import TeachingAssignment
from apps.academics.selectors import classrooms
from apps.accounts.models import User
from apps.students.selectors import roster

from .models import Exam


def exams(user):
    qs = Exam.objects.filter(classroom__in=classrooms(user)).select_related(
        "classroom__branch", "classroom__year", "subject", "published_by"
    )
    if user.role == User.Role.STUDENT:
        return qs.filter(
            status=Exam.Status.PUBLISHED, marks__enrollment__student__user=user
        ).distinct()
    if user.role == User.Role.TEACHER:
        assigned = TeachingAssignment.objects.filter(teacher=user).values(
            "classroom_id", "subject_id"
        )
        condition = Q(classroom__homeroom_teacher=user)
        for row in assigned:
            condition |= Q(classroom_id=row["classroom_id"], subject_id=row["subject_id"])
        return qs.filter(condition).distinct()
    return qs


def mark_sheet(exam):
    """The students on the class list on the exam date, and their saved marks by enrollment id."""
    return {
        "roster": list(roster(exam.classroom, exam.date)),
        "marks": {
            m.enrollment_id: m
            for m in exam.marks.select_related("enrollment__student__user", "exam")
        },
    }


def mark_summary(marks):
    marks = list(marks)
    possible = sum((m.exam.max_marks for m in marks), Decimal(0))
    earned = sum((m.score or Decimal(0) for m in marks), Decimal(0))
    return {
        "count": len(marks),
        "earned": earned,
        "possible": possible,
        "percentage": round(earned / possible * 100, 1) if possible else None,
        "passed": sum(m.passed for m in marks),
    }
