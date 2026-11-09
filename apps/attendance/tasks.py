from celery import shared_task
from django.urls import reverse

from apps.accounts.models import User
from apps.communication.models import Notification
from apps.communication.services import notify
from apps.students.models import Student
from apps.students.selectors import family

from .models import Attendance, AttendanceSession, LeaveRequest
from .selectors import leave_enrollment


@shared_task
def alert_absent_families(session_id, enrollment_ids):
    """Tell each newly absent student and their guardians, in the app and by email.

    Safe to run twice (one alert per student per day). A student whose register was corrected
    to present before this ran is skipped.
    """
    session = AttendanceSession.objects.select_related("classroom__grade").get(pk=session_id)
    still_absent = Attendance.objects.filter(
        session=session, enrollment_id__in=enrollment_ids, status=Attendance.Status.ABSENT
    ).select_related("enrollment__student__user")
    classroom = session.classroom
    sent = 0
    for record in still_absent:
        student = record.enrollment.student
        sent += notify(
            family(Student.objects.filter(pk=student.pk)),
            Notification.Kind.ABSENCE,
            f"absence:{record.enrollment_id}:{session.date.isoformat()}",
            f"{student.user.display_name} was marked absent today",
            f"Class {classroom.grade}-{classroom.section}, {session.date:%d %b %Y}. "
            "If you weren't expecting this, please contact the school.",
            url=reverse("student_report", args=[student.pk]),
            email=True,
        )
    return sent


@shared_task
def correct_absence_alerts(session_id, enrollment_ids):
    """Today's register was corrected: tell whoever got an absence alert for these students that
    they are not absent after all. Only people who were alerted hear about it; once each."""
    session = AttendanceSession.objects.get(pk=session_id)
    corrected = (
        Attendance.objects.filter(session=session, enrollment_id__in=enrollment_ids)
        .exclude(status=Attendance.Status.ABSENT)
        .select_related("enrollment__student__user")
    )
    sent = 0
    for record in corrected:
        alert = f"absence:{record.enrollment_id}:{session.date.isoformat()}"
        alerted = User.objects.filter(notifications__key=alert)
        student = record.enrollment.student
        sent += notify(
            alerted,
            Notification.Kind.ABSENCE,
            f"absence-corrected:{record.enrollment_id}:{session.date.isoformat()}",
            f"Correction: {student.user.display_name} is not absent today",
            f"The register for {session.date:%d %b %Y} was corrected: "
            f"{record.get_status_display().lower()}. Please ignore the earlier absence alert.",
            url=reverse("student_report", args=[student.pk]),
            email=True,
        )
    return sent


@shared_task
def notify_leave_requested(leave_id):
    """Tell the class teacher a parent asked for leave. Safe to run twice."""
    leave = LeaveRequest.objects.select_related("student__user").get(pk=leave_id)
    enrollment = leave_enrollment(leave)
    teacher = enrollment.classroom.homeroom_teacher if enrollment else None
    if teacher is None:
        return 0
    return notify(
        [teacher],
        Notification.Kind.LEAVE,
        f"leave-requested:{leave.pk}",
        f"Leave request for {leave.student.user.display_name}",
        f"{leave.starts_on:%d %b} to {leave.ends_on:%d %b %Y}: {leave.reason}",
        url=reverse("leave_requests"),
        email=True,
    )


@shared_task
def notify_leave_decided(leave_id):
    """Tell the parent who asked, and the student, what was decided. Safe to run twice."""
    leave = LeaveRequest.objects.select_related("student__user", "requested_by").get(pk=leave_id)
    verdict = "approved" if leave.status == LeaveRequest.Status.APPROVED else "not approved"
    return notify(
        [leave.requested_by, leave.student.user],
        Notification.Kind.LEAVE,
        f"leave-decided:{leave.pk}",
        f"Leave {verdict} for {leave.student.user.display_name}",
        f"{leave.starts_on:%d %b} to {leave.ends_on:%d %b %Y}. {leave.decision_note}".strip(),
        url=reverse("leave_requests"),
        email=True,
    )
