from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.academics.models import Classroom
from apps.audit.services import audit
from apps.core.exceptions import Conflict
from apps.students.selectors import roster

from .models import Attendance, AttendanceSession
from .policies import can_attend


@transaction.atomic
def save_register(actor, classroom, day, statuses, expected_version, reason=""):
    # The classroom lock also serializes first creation when no register exists yet.
    classroom = Classroom.objects.select_for_update().get(pk=classroom.pk)
    if not can_attend(actor, classroom):
        raise PermissionDenied
    if day > timezone.localdate() or not classroom.year.starts_on <= day <= classroom.year.ends_on:
        raise ValidationError("Attendance date is outside the permitted range.")
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
    return session
