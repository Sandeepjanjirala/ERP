from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.academics.models import Classroom
from apps.audit.services import audit
from apps.core.exceptions import Conflict
from apps.core.jobs import run_after_commit
from apps.students.selectors import roster

from .models import Attendance, AttendanceSession, LeaveRequest
from .policies import can_attend, can_request_leave
from .selectors import leave_enrollment
from .tasks import alert_absent_families, notify_leave_decided, notify_leave_requested


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


@transaction.atomic
def request_leave(parent, leave):
    """A parent asks for days off for their child; the class teacher is notified."""
    if not can_request_leave(parent, leave.student):
        raise PermissionDenied
    enrollment = leave_enrollment(leave)
    if enrollment is None:
        raise ValidationError({"starts_on": "Your child isn't in a class on the first day."})
    # Lock the student's requests so two quick submissions can't both pass the overlap check.
    list(LeaveRequest.objects.select_for_update().filter(student=leave.student))
    if LeaveRequest.objects.filter(
        student=leave.student,
        status__in=[LeaveRequest.Status.PENDING, LeaveRequest.Status.APPROVED],
        starts_on__lte=leave.ends_on,
        ends_on__gte=leave.starts_on,
    ).exists():
        raise ValidationError("These days overlap another request for the same child.")
    leave.requested_by = parent
    leave.status = LeaveRequest.Status.PENDING
    leave.save()
    audit(parent, enrollment.classroom.branch, "leave.requested", leave)
    run_after_commit(notify_leave_requested, leave.pk)
    return leave


@transaction.atomic
def decide_leave(actor, leave, approve, note=""):
    """Approve or refuse a leave request. Approval turns recorded absences into "Excused".

    The same people who record the class's register decide: its class teacher, the branch
    admin, or a super admin.
    """
    enrollment = leave_enrollment(leave)
    # The classroom lock is the register lock: no register save can interleave with this.
    classroom = Classroom.objects.select_for_update().get(pk=enrollment.classroom_id)
    leave = LeaveRequest.objects.select_for_update().get(pk=leave.pk)
    if not can_attend(actor, classroom):
        raise PermissionDenied
    if leave.status != LeaveRequest.Status.PENDING:
        raise ValidationError("This request has already been decided.")
    if not approve and not note.strip():
        raise ValidationError({"decision_note": "Say why the request is not approved."})
    leave.status = LeaveRequest.Status.APPROVED if approve else LeaveRequest.Status.REJECTED
    leave.decided_by = actor
    leave.decided_at = timezone.now()
    leave.decision_note = note
    leave.save()
    excused = _excuse_recorded_absences(actor, leave, enrollment) if approve else []
    audit(
        actor,
        classroom.branch,
        f"leave.{leave.status}",
        leave,
        {"note": note, "excused_days": excused},
    )
    run_after_commit(notify_leave_decided, leave.pk)
    return leave


def _excuse_recorded_absences(actor, leave, enrollment):
    """On saved registers within the leave, "Absent" becomes "Excused". Present stays present.

    Each changed register gets a new version, so a teacher with it open must reload rather
    than overwrite the change.
    """
    excused = []
    sessions = AttendanceSession.objects.select_for_update().filter(
        classroom_id=enrollment.classroom_id, date__range=(leave.starts_on, leave.ends_on)
    )
    for session in sessions.order_by("date"):
        changed = session.records.filter(
            enrollment=enrollment, status=Attendance.Status.ABSENT
        ).update(status=Attendance.Status.EXCUSED)
        if changed:
            session.version += 1
            session.recorded_by = actor
            session.save()
            excused.append(session.date.isoformat())
    return excused
