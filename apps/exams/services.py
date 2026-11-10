from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.academics.models import Classroom
from apps.audit.services import audit
from apps.core.exceptions import Conflict
from apps.core.jobs import run_after_commit
from apps.students.selectors import roster

from .models import Exam, GradeBand, GradingScale, Mark
from .policies import can_create_exam, can_manage_grading, can_mark, can_publish
from .selectors import current_scale
from .tasks import announce_results


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
    students = {enrollment.pk: enrollment for enrollment in roster(exam.classroom, exam.date)}
    if set(entries) != set(students):
        raise ValidationError("The student roster changed. Reload this page.")
    existing = {mark.enrollment_id: mark for mark in exam.marks.all()}
    before = {
        str(m.enrollment_id): {
            "score": str(m.score) if m.score is not None else None,
            "absent": m.absent,
        }
        for m in existing.values()
    }
    # Written in bulk (a few queries, not several per student), each mark checked first by the
    # same rules as Mark.save(): score range, a score or absent, the exam's class. The exam and
    # enrollment are rows just loaded under lock, so their existence isn't queried again.
    new, changed, cleared = [], [], []
    for enrollment_id, (score, absent) in entries.items():
        mark = existing.get(enrollment_id)
        if score is None and not absent:
            if mark:
                cleared.append(mark.pk)
            continue
        if mark is None:
            mark = Mark(exam=exam, enrollment_id=enrollment_id)
            new.append(mark)
        elif (mark.score, mark.absent) != (score, absent):
            changed.append(mark)
        else:
            continue
        mark.exam, mark.enrollment = exam, students[enrollment_id]
        mark.score, mark.absent = score, absent
        mark.full_clean(
            exclude=["exam", "enrollment"], validate_unique=False, validate_constraints=False
        )
    Mark.objects.filter(pk__in=cleared).delete()
    Mark.objects.bulk_create(new)
    Mark.objects.bulk_update(changed, ["score", "absent"])
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
    # Publishing freezes the scale in force now; a reopened exam is a draft again, which shows
    # whatever scale is current until it is published again.
    exam.grading_scale = current_scale() if action == "publish" else None
    exam.save()
    details = {"from": old, "to": target, "reason": reason}
    if action == "publish":
        details["grading_scale"] = exam.grading_scale.version if exam.grading_scale else None
    audit(actor, exam.classroom.branch, f"exam.{action}", exam, details)
    if action == "publish":
        run_after_commit(announce_results, exam.pk, exam.version)
    return exam


@transaction.atomic
def create_exam(actor, exam):
    """Save a new exam (always a draft) and record who created it."""
    if not can_create_exam(actor, exam.classroom, exam.subject):
        raise PermissionDenied
    exam.save()
    audit(actor, exam.classroom.branch, "exam.created", exam)
    return exam


# The bands most Indian schools use (CBSE): a starting point for the first scale.
DEFAULT_BANDS = [
    ("A1", 91), ("A2", 81), ("B1", 71), ("B2", 61), ("C1", 51), ("C2", 41), ("D", 33), ("E", 0),
]  # fmt: skip


def _check_bands(rows):
    bands = [(row["label"].strip(), Decimal(row["min_percent"])) for row in rows]
    if len(bands) < 2:
        raise ValidationError("A grading scale needs at least two bands.")
    labels = [label for label, _ in bands]
    if not all(labels):
        raise ValidationError("Every band needs a label.")
    if len({label.casefold() for label in labels}) != len(labels):
        raise ValidationError("Each band needs its own label.")
    minimums = [minimum for _, minimum in bands]
    if any(not 0 <= minimum <= 100 for minimum in minimums):
        raise ValidationError("Band minimums are percentages from 0 to 100.")
    if len(set(minimums)) != len(minimums):
        raise ValidationError("Two bands can't start at the same percentage.")
    if min(minimums) != 0:
        raise ValidationError("The lowest band must start at 0%, so every result gets a grade.")
    return sorted(bands, key=lambda band: band[1], reverse=True)


@transaction.atomic
def save_grading_scale(actor, rows):
    """Save `rows` (label, min_percent) as the next version of the grading scale.

    Earlier versions are never changed: exams already published keep the version they were
    published with. Drafts and exams awaiting approval show the new version at once.
    """
    if not can_manage_grading(actor):
        raise PermissionDenied
    bands = _check_bands(rows)
    latest = GradingScale.objects.select_for_update().order_by("-version").first()
    scale = GradingScale.objects.create(
        version=(latest.version if latest else 0) + 1, created_by=actor
    )
    GradeBand.objects.bulk_create(
        GradeBand(scale=scale, label=label, min_percent=minimum) for label, minimum in bands
    )
    audit(
        actor,
        None,
        "exams.grading_scale.saved",
        scale,
        {
            "version": scale.version,
            "bands": [f"{label} from {minimum}%" for label, minimum in bands],
        },
    )
    return scale
