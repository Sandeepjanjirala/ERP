"""Read queries and summaries for exams and marks."""

from decimal import Decimal

from django.db.models import Count, Q

from apps.academics.models import TeachingAssignment
from apps.academics.selectors import classrooms
from apps.accounts.models import User
from apps.students.selectors import roster

from .models import Exam, GradingScale


def exams(user):
    if user.role not in User.ACADEMIC:
        return Exam.objects.none()  # accountants work with fees, not marks
    qs = Exam.objects.filter(classroom__in=classrooms(user)).select_related(
        "classroom__branch",
        "classroom__year",
        "classroom__grade",
        "term",
        "subject",
        "published_by",
    )
    # Families see published exams only, and only those their child sat.
    if user.role == User.Role.STUDENT:
        return qs.filter(
            status=Exam.Status.PUBLISHED, marks__enrollment__student__user=user
        ).distinct()
    if user.role == User.Role.PARENT:
        return qs.filter(
            status=Exam.Status.PUBLISHED,
            marks__enrollment__student__guardian_links__guardian__user=user,
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


def current_scale():
    """The newest version of the grading scale, with its bands, or None before one is saved."""
    return GradingScale.objects.prefetch_related("bands").order_by("-version").first()


def grading_scales():
    """Every version, newest first, with how many exams were published with it."""
    return (
        GradingScale.objects.select_related("created_by")
        .prefetch_related("bands")
        .annotate(exam_count=Count("exams"))
        .order_by("-version")
    )


def with_grades(marks, current=None):
    """Give each mark a `grade_label` (see Mark.grade): its exam's frozen scale once published,
    otherwise `current`."""
    for mark in marks:
        mark.grade_label = mark.grade(current)
    return marks


def overall_grade(marks, percentage):
    """The band of an overall percentage, by the scale of the most recently published exam among
    `marks`, so it changes only when results do, never with a later scale. None if no published
    exam carries a scale."""
    graded = [
        m.exam
        for m in marks
        if m.exam.status == Exam.Status.PUBLISHED and m.exam.grading_scale_id is not None
    ]
    if not graded or percentage is None:
        return None
    latest = max(
        graded, key=lambda exam: (exam.published_at is not None, exam.published_at, exam.pk)
    )
    return latest.grading_scale.band_for(percentage)
