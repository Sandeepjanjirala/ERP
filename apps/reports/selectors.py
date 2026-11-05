"""Read queries for reports, limited to what the user may see."""

from django.shortcuts import get_object_or_404

from apps.academics.models import AcademicYear
from apps.attendance.selectors import attendance_rows, attendance_summary
from apps.exams.models import Exam, Mark
from apps.exams.selectors import exams, mark_summary
from apps.students.selectors import enrollments


def student_report(user, student, year_id=None):
    """A student's enrollments, published results and attendance for one academic year.

    `year_id` picks the year (an unknown id is a 404); by default it is the latest year the
    student was enrolled in. Only published results are included, whoever is asking.
    """
    student_enrollments = enrollments(user).filter(student=student)
    if year_id and str(year_id).isdigit():
        year = get_object_or_404(AcademicYear, pk=year_id)
    else:
        year = AcademicYear.objects.filter(enrollment__in=student_enrollments).distinct().first()
    if year:
        student_enrollments = student_enrollments.filter(year=year)
    marks = list(
        Mark.objects.filter(
            enrollment__in=student_enrollments,
            exam__in=exams(user).filter(status=Exam.Status.PUBLISHED),
        ).select_related("exam__subject", "exam__classroom")
    )
    rows = (
        attendance_rows(user).filter(enrollment__in=student_enrollments).order_by("-session__date")
    )
    return {
        "enrollments": student_enrollments,
        "marks": marks,
        "summary": mark_summary(marks),
        "attendance_rows": rows,
        "attendance_summary": attendance_summary(rows),
        "years": AcademicYear.objects.filter(enrollment__student=student).distinct(),
        "selected_year": year,
    }
