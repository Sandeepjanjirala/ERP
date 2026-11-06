"""Read queries and summaries for attendance."""

from django.db.models import Q

from apps.students.models import Enrollment
from apps.students.selectors import enrollments, roster, students

from .models import Attendance, AttendanceSession, LeaveRequest

# Students below this attendance rate (%) are flagged on reports and dashboards.
MINIMUM_ATTENDANCE = 75


def daily_register(classroom, day):
    """The class list that day, the saved register (or None), its statuses, and who is on leave.

    `on_leave` holds the enrollments with approved leave that day: the register suggests
    "Excused" for them until it is saved.
    """
    session = AttendanceSession.objects.filter(classroom=classroom, date=day).first()
    enrolled = list(roster(classroom, day))
    on_leave = set(
        LeaveRequest.objects.filter(
            status=LeaveRequest.Status.APPROVED,
            starts_on__lte=day,
            ends_on__gte=day,
            student__enrollments__in=enrolled,
        ).values_list("student__enrollments", flat=True)
    ) & {enrollment.pk for enrollment in enrolled}
    return {
        "roster": enrolled,
        "session": session,
        "statuses": dict(session.records.values_list("enrollment_id", "status")) if session else {},
        "on_leave": on_leave,
    }


def leave_requests(user):
    """Leave requests for the students the user may see, newest first."""
    return LeaveRequest.objects.filter(student__in=students(user)).select_related(
        "student__user", "requested_by", "decided_by"
    )


def leave_enrollment(leave):
    """The student's class enrollment on the first day of leave, or None if not enrolled then."""
    return (
        Enrollment.objects.filter(student_id=leave.student_id, joined_on__lte=leave.starts_on)
        .filter(Q(left_on__isnull=True) | Q(left_on__gte=leave.starts_on))
        .select_related("classroom__branch", "classroom__homeroom_teacher")
        .first()
    )


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
    rate = round(100 * attended / denominator, 1) if denominator else None
    return {
        **counts,
        "total": sum(counts.values()),
        "rate": rate,
        "below_minimum": rate is not None and rate < MINIMUM_ATTENDANCE,
    }


def leave_enrollments(leaves):
    """leave_enrollment() for many requests with one query: {leave id: enrollment or None}."""
    leaves = list(leaves)
    candidates = list(
        Enrollment.objects.filter(student_id__in={leave.student_id for leave in leaves})
        .select_related("classroom__branch", "classroom__homeroom_teacher")
        .order_by("joined_on", "pk")
    )
    return {
        leave.pk: next(
            (
                e
                for e in candidates
                if e.student_id == leave.student_id
                and e.joined_on <= leave.starts_on
                and (e.left_on is None or e.left_on >= leave.starts_on)
            ),
            None,
        )
        for leave in leaves
    }
