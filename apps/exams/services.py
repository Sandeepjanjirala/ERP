from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.academics.models import Classroom
from apps.audit.services import audit
from apps.core.exceptions import Conflict
from apps.students.selectors import roster

from .models import Exam, Mark
from .policies import can_create_exam, can_mark, can_publish


@transaction.atomic
def save_marks(actor, exam, entries, expected_version):
    Classroom.objects.select_for_update().get(pk=exam.classroom_id)
    exam = Exam.objects.select_for_update().get(pk=exam.pk)
    if not can_mark(actor, exam):
        raise PermissionDenied
    if exam.version != expected_version:
        raise Conflict("This mark sheet changed. Reload before saving.")
    if exam.status != Exam.Status.DRAFT:
        raise ValidationError(
            "Marks are locked after submission. Ask the principal to reopen this exam."
        )
    eligible = set(roster(exam.classroom, exam.date).values_list("pk", flat=True))
    if set(entries) != eligible:
        raise ValidationError("The student roster changed. Reload this page.")
    before = {
        str(m.enrollment_id): {
            "score": str(m.score) if m.score is not None else None,
            "absent": m.absent,
        }
        for m in exam.marks.all()
    }
    for enrollment_id, entry in entries.items():
        score, absent = entry
        if score is None and not absent:
            Mark.objects.filter(exam=exam, enrollment_id=enrollment_id).delete()
        else:
            Mark.objects.update_or_create(
                exam=exam, enrollment_id=enrollment_id, defaults={"score": score, "absent": absent}
            )
    exam.version += 1
    exam.save()
    audit(
        actor,
        exam.classroom.branch,
        "marks.saved",
        exam,
        {
            "before": before,
            "after": {
                str(k): {"score": str(v[0]) if v[0] is not None else None, "absent": v[1]}
                for k, v in entries.items()
            },
        },
    )


@transaction.atomic
def transition_exam(actor, exam, action, expected_version, reason=""):
    Classroom.objects.select_for_update().get(pk=exam.classroom_id)
    exam = Exam.objects.select_for_update().get(pk=exam.pk)
    if exam.version != expected_version:
        raise Conflict("This exam changed. Reload before continuing.")
    if action == "submit":
        if not can_mark(actor, exam):
            raise PermissionDenied
        if exam.status != Exam.Status.DRAFT:
            raise ValidationError("Only draft exams can be submitted.")
        target = Exam.Status.SUBMITTED
    elif action == "publish":
        if not can_publish(actor, exam):
            raise PermissionDenied
        if exam.status != Exam.Status.SUBMITTED:
            raise ValidationError("Submit the exam for review before publishing.")
        target = Exam.Status.PUBLISHED
    elif action == "reopen":
        if not can_publish(actor, exam):
            raise PermissionDenied
        if exam.status == Exam.Status.DRAFT or not reason.strip():
            raise ValidationError("Reopening requires a locked exam and a correction reason.")
        target = Exam.Status.DRAFT
    else:
        raise ValidationError("Unknown exam action.")
    if action in ("submit", "publish"):
        if exam.date > timezone.localdate():
            raise ValidationError("An upcoming exam cannot be submitted or published.")
        eligible = set(roster(exam.classroom, exam.date).values_list("pk", flat=True))
        if not eligible or set(exam.marks.values_list("enrollment_id", flat=True)) != eligible:
            raise ValidationError(
                "Enter a score or absence for every enrolled student before continuing."
            )
    old = exam.status
    exam.status = target
    exam.version += 1
    exam.published_by = actor if action == "publish" else None
    exam.published_at = timezone.now() if action == "publish" else None
    exam.save()
    audit(
        actor,
        exam.classroom.branch,
        f"exam.{action}",
        exam,
        {"from": old, "to": target, "reason": reason},
    )
    return exam


@transaction.atomic
def create_exam(actor, exam):
    """Save a new exam (always a draft) and record who created it."""
    if not can_create_exam(actor, exam.classroom, exam.subject):
        raise PermissionDenied
    exam.save()
    audit(actor, exam.classroom.branch, "exam.created", exam)
    return exam
