from celery import shared_task
from django.urls import reverse

from apps.communication.models import Notification
from apps.communication.services import notify
from apps.students.models import Student
from apps.students.selectors import family

from .models import Attendance, AttendanceSession


@shared_task
def alert_absent_families(session_id, enrollment_ids):
    """Tell each newly absent student and their guardians, in the app and by email.

    Safe to run twice (one alert per student per day). A student whose register was corrected
    to present before this ran is skipped.
    """
    session = AttendanceSession.objects.select_related("classroom").get(pk=session_id)
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
