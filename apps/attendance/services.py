from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.academics.models import Classroom
from apps.audit.services import audit
from apps.core.exceptions import Conflict
from apps.core.jobs import run_after_commit
from apps.students.selectors import roster

from .models import Attendance, AttendanceSession
from .policies import can_attend
from .tasks import alert_absent_families


def register_date_error(classroom, day):
    """Why a register can't exist for this day, or None: not in the future, inside the year."""
    if day > timezone.localdate():
        return "Future attendance is not allowed."
    if not classroom.year.starts_on <= day <= classroom.year.ends_on:
        return "Select a date within the classroom academic year."
    return None


@transaction.atomic
def save_register(actor, classroom, day, statuses, expected_version, reason=""):
    # The classroom lock also serializes first creation when no register exists yet.
    classroom = Classroom.objects.select_for_update().get(pk=classroom.pk)
    if not can_attend(actor, classroom):
        raise PermissionDenied
    if problem := register_date_error(classroom, day):
        raise ValidationError(problem)
    eligible = set(roster(classroom, day).values_list("pk", flat=True))
    if (
        not eligible
        or set(statuses) != eligible
        or any(v not in Attendance.Status.values for v in statuses.values())
    ):
        raise ValidationError("Mark every enrolled student using a valid attendance status.")
    session = (
        AttendanceSession.objects.select_for_update().filter(classroom=classroom, date=day).first()
    )
    if (session.version if session else 0) != expected_version:
        raise Conflict("Another user changed this register. Reload before saving.")
    old = {}
    if session:
        if not reason.strip():
            raise ValidationError("Enter a reason for correcting this register.")
        old = {str(k): v for k, v in session.records.values_list("enrollment_id", "status")}
        session.version += 1
        session.recorded_by = actor
        session.save()
    else:
        session = AttendanceSession.objects.create(classroom=classroom, date=day, recorded_by=actor)
    for enrollment_id, status in statuses.items():
        Attendance.objects.update_or_create(
            session=session, enrollment_id=enrollment_id, defaults={"status": status}
        )
    audit(
        actor,
        classroom.branch,
        "attendance.saved",
        f"{classroom} · {day}",
        {"before": old, "after": {str(k): v for k, v in statuses.items()}, "reason": reason},
    )
    # Families hear about today's absences only: a correction to an old register sends nothing.
    newly_absent = sorted(
        enrollment_id
        for enrollment_id, status in statuses.items()
        if status == Attendance.Status.ABSENT and old.get(str(enrollment_id)) != status
    )
    if day == timezone.localdate() and newly_absent:
        run_after_commit(alert_absent_families, session.pk, newly_absent)
    return session
