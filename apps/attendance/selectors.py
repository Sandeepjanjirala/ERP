"""Read queries and summaries for attendance."""

from apps.students.selectors import enrollments

from .models import Attendance


def attendance_rows(user):
    qs = Attendance.objects.filter(enrollment__in=enrollments(user)).select_related(
        "session", "enrollment__student__user"
    )
    return qs


def attendance_summary(rows):
    counts = {v: 0 for v in Attendance.Status.values}
    for status in rows.values_list("status", flat=True):
        counts[status] += 1
    denominator = counts["P"] + counts["L"] + counts["A"]
    return {
        **counts,
        "total": sum(counts.values()),
        "rate": round(100 * (counts["P"] + counts["L"]) / denominator, 1) if denominator else None,
    }
