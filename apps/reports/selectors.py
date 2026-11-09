"""Read queries for reports, limited to what the user may see."""

from collections import defaultdict
from datetime import timedelta

from django.db.models import Count, Exists, OuterRef, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.academics.models import AcademicYear, TeachingAssignment
from apps.academics.selectors import classrooms
from apps.accounts.models import User
from apps.attendance.models import Attendance, AttendanceSession, LeaveRequest
from apps.attendance.selectors import (
    MINIMUM_ATTENDANCE,
    attendance_rows,
    attendance_summary,
    leave_requests,
)
from apps.communication.selectors import announcements
from apps.core.cache import cached
from apps.exams.models import Exam, Mark
from apps.exams.selectors import exams, mark_summary
from apps.students.selectors import enrollments, students


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
        ).select_related("exam__subject", "exam__term", "exam__classroom__grade")
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


def published_marks(user, year_id=None, branch=None):
    """Every published mark the user may see, optionally for one year and one branch."""
    permitted = exams(user).filter(status=Exam.Status.PUBLISHED)
    if year_id and str(year_id).isdigit():
        permitted = permitted.filter(classroom__year_id=year_id)
    if branch:
        permitted = permitted.filter(classroom__branch=branch)
    return list(
        Mark.objects.filter(exam__in=permitted).select_related(
            "exam__subject",
            "exam__classroom__branch",
            "exam__classroom__grade",
            "enrollment__student__user",
        )
    )


def subject_performance(marks):
    """Pass counts and percentages per branch and subject, in name order."""
    groups = defaultdict(list)
    for mark in marks:
        groups[(mark.exam.classroom.branch.name, mark.exam.subject.name)].append(mark)
    return [
        {"branch": branch, "name": subject, **mark_summary(group)}
        for (branch, subject), group in sorted(groups.items())
    ]


def overview(user, branch=None):
    """The dashboard: headline numbers, up to 12 classes with today's register, recent exams."""
    classes = classrooms(user)
    people = students(user)
    exams_qs = exams(user)
    attendance = attendance_rows(user)
    if branch:
        classes = classes.filter(branch=branch)
        people = people.filter(user__branch=branch)
        exams_qs = exams_qs.filter(classroom__branch=branch)
        attendance = attendance.filter(session__classroom__branch=branch)
    today = timezone.localdate()
    stats = {
        "students": people.filter(user__is_active=True).count(),
        "classes": classes.count(),
        "pending": exams_qs.filter(status=Exam.Status.SUBMITTED).count(),
        "attendance": attendance_summary(attendance.filter(session__date=today))["rate"],
    }
    class_rows = list(
        classes.annotate(
            student_count=Count(
                "enrollments", filter=Q(enrollments__left_on__isnull=True), distinct=True
            )
        )[:12]
    )
    sessions = {
        s.classroom_id: s
        for s in AttendanceSession.objects.filter(classroom__in=class_rows, date=today)
    }
    for classroom in class_rows:
        classroom.register = sessions.get(classroom.pk)
    return {
        "today": today,
        "stats": stats,
        "class_rows": class_rows,
        "recent_exams": exams_qs[:5],
    }


# Dashboards. The heavy numbers (over every attendance row) are cached; each key carries
# register_version(), which changes whenever a register in scope is saved or corrected.

TREND_DAYS = 30


def register_version(classes, since=None):
    """A cheap fingerprint of the registers in these classes, read from the small registers
    table rather than the attendance rows.

    A new register raises the count; every correction (and every absence excused by approved
    leave) raises that register's version number, so the sum changes too. No clock is involved,
    so two saves within the same millisecond still give different fingerprints.
    """
    sessions = AttendanceSession.objects.filter(classroom__in=classes)
    if since:
        sessions = sessions.filter(date__gte=since)
    version = sessions.aggregate(registers=Count("pk"), edits=Sum("version"))
    return f"{version['registers']}/{version['edits']}"


def _rates(rows, group):
    """Attendance rate per value of `group`: present and late, out of present, late and absent."""
    grouped = (
        rows.values(group)
        .annotate(
            attended=Count(
                "pk", filter=Q(status__in=[Attendance.Status.PRESENT, Attendance.Status.LATE])
            ),
            absent=Count("pk", filter=Q(status=Attendance.Status.ABSENT)),
        )
        .order_by(group)
    )
    return [
        (
            row[group],
            round(100 * row["attended"] / (row["attended"] + row["absent"]), 1)
            if row["attended"] + row["absent"]
            else None,
        )
        for row in grouped
    ]


def attendance_trend(user, branch=None):
    """Daily attendance rate over the last 30 days in the user's scope, for the trend chart."""
    since = timezone.localdate() - timedelta(days=TREND_DAYS - 1)
    classes = classrooms(user)
    rows = attendance_rows(user).filter(session__date__gte=since)
    if branch:
        classes, rows = (
            classes.filter(branch=branch),
            rows.filter(session__classroom__branch=branch),
        )

    def compute():
        return [
            {"date": day.isoformat(), "rate": rate} for day, rate in _rates(rows, "session__date")
        ]

    key = (user.pk, branch.pk if branch else "", since, register_version(classes, since))
    return cached("attendance-trend", key, compute)


def low_attendance(user, branch=None, limit=10):
    """Students in scope whose attendance is below 75%, lowest first (at most `limit`)."""
    classes = classrooms(user)
    scope = enrollments(user)
    if branch:
        classes, scope = classes.filter(branch=branch), scope.filter(classroom__branch=branch)

    def compute():
        rates = _rates(Attendance.objects.filter(enrollment__in=scope), "enrollment")
        flagged = sorted(
            (rate, pk) for pk, rate in rates if rate is not None and rate < MINIMUM_ATTENDANCE
        )[:limit]
        found = scope.in_bulk([pk for _, pk in flagged])
        return [
            {
                "student_id": found[pk].student_id,
                "name": found[pk].student.user.display_name,
                "admission_number": found[pk].student.admission_number,
                "classroom": f"{found[pk].classroom.grade}-{found[pk].classroom.section}",
                "rate": rate,
            }
            for rate, pk in flagged
        ]

    key = (user.pk, branch.pk if branch else "", limit, register_version(classes))
    return cached("low-attendance", key, compute)


def branch_comparison(user):
    """Super admins: each branch's attendance rate over the last 30 days."""
    if not user.system_admin:
        return []
    since = timezone.localdate() - timedelta(days=TREND_DAYS - 1)
    rows = Attendance.objects.filter(session__date__gte=since)

    def compute():
        return [
            {"branch": name, "rate": rate}
            for name, rate in _rates(rows, "session__classroom__branch__name")
        ]

    key = (since, register_version(classrooms(user), since))
    return cached("branch-comparison", key, compute)


def to_do(user):
    """What is waiting for this person: mark sheets, approvals and leave requests."""
    pending_leave = leave_requests(user).filter(status=LeaveRequest.Status.PENDING)
    if user.role == User.Role.TEACHER:
        # Only requests for their own class: they are the one who decides.
        pending_leave = pending_leave.filter(
            student__enrollments__classroom__homeroom_teacher=user,
            student__enrollments__left_on__isnull=True,
        ).distinct()
    elif user.role == User.Role.PRINCIPAL:
        pending_leave = pending_leave.none()  # class teachers and admins decide leave
    drafts = exams(user).filter(status=Exam.Status.DRAFT)
    if user.role == User.Role.TEACHER:
        drafts = drafts.filter(
            Exists(
                TeachingAssignment.objects.filter(
                    teacher=user, classroom=OuterRef("classroom"), subject=OuterRef("subject")
                )
            )
        )
    elif not user.system_admin:
        drafts = drafts.none()  # only teachers (and super admins) enter marks
    awaiting = exams(user).filter(status=Exam.Status.SUBMITTED)
    if not (user.system_admin or user.role == User.Role.PRINCIPAL):
        awaiting = awaiting.none()  # only principals publish
    return {
        "drafts": list(drafts.order_by("date", "pk")[:5]),
        "drafts_count": drafts.count(),
        "awaiting": list(awaiting.order_by("date", "pk")[:5]),
        "awaiting_count": awaiting.count(),
        "leave": list(pending_leave.order_by("starts_on", "pk")[:5]),
        "leave_count": pending_leave.count(),
    }


def family_overview(user, student):
    """A student's or parent's dashboard for one child: this year's attendance and results."""
    report = student_report(user, student)
    return {
        **report,
        "recent_attendance": list(report["attendance_rows"][:10]),
        "latest_results": sorted(report["marks"], key=lambda m: (m.exam.date, m.pk), reverse=True)[
            :5
        ],
        "announcements": list(announcements(user)[:3]),
        "leave": list(leave_requests(user).filter(student=student)[:3]),
    }
