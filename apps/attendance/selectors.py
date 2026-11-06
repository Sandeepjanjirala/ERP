"""Read queries and summaries for attendance."""

from apps.students.selectors import enrollments, roster

from .models import Attendance, AttendanceSession


def daily_register(classroom, day):
    """The students on the class list that day, the saved register (or None) and their statuses."""
    session = AttendanceSession.objects.filter(classroom=classroom, date=day).first()
    return {
        "roster": list(roster(classroom, day)),
        "session": session,
        "statuses": dict(session.records.values_list("enrollment_id", "status")) if session else {},
    }


def attendance_rows(user):
    qs = Attendance.objects.filter(enrollment__in=enrollments(user)).select_related(
        "session", "enrollment__student__user"
    )
    return qs


def attendance_summary(rows):
    counts = {v: 0 for v in Attendance.Status.values}
    for status in rows.values_list("status", flat=True):
        counts[status] += 1
    # Present and late count as attended; excused days are left out of the percentage.
    attended = counts[Attendance.Status.PRESENT] + counts[Attendance.Status.LATE]
    denominator = attended + counts[Attendance.Status.ABSENT]
    return {
        **counts,
        "total": sum(counts.values()),
        "rate": round(100 * attended / denominator, 1) if denominator else None,
    }
