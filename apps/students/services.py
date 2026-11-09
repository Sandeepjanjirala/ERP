import secrets
from datetime import date, timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.academics.models import Classroom
from apps.accounts.models import User
from apps.accounts.services import create_account, set_access
from apps.audit.services import audit
from apps.core.jobs import run_after_commit

from .models import Enrollment, Guardian, ImportBatch, Student, StudentGuardian
from .policies import can_enroll, can_import, can_manage_guardians, can_promote
from .tasks import send_access_ending_notice, send_import_invites


@transaction.atomic
def admit_student(actor, user, password, admission_number, classroom, joined_on):
    """Create a student's login, profile and first enrollment together, or none of them."""
    if not can_enroll(actor, classroom):
        raise PermissionDenied
    # Lock the classroom so a register or exam can't be completed while its roster changes.
    Classroom.objects.select_for_update().get(pk=classroom.pk)
    create_account(actor, user, password)
    student = Student.objects.create(user=user, admission_number=admission_number)
    Enrollment.objects.create(
        student=student, classroom=classroom, year=classroom.year, joined_on=joined_on
    )
    return student


@transaction.atomic
def enroll(actor, enrollment):
    """Enroll an existing student in a classroom for the classroom's academic year."""
    if not can_enroll(actor, enrollment.classroom):
        raise PermissionDenied
    Classroom.objects.select_for_update().get(pk=enrollment.classroom_id)
    enrollment.year = enrollment.classroom.year
    enrollment.save()
    audit(actor, enrollment.classroom.branch, "setup.enrollment.saved", enrollment)
    return enrollment


@transaction.atomic
def link_guardian(actor, student, parent, relationship, make_primary=False):
    """Link an existing parent account to a student, e.g. a second child of the same family.

    A student's first guardian always becomes the primary one.
    """
    # Lock the student so two admins adding the first guardian can't both make them primary.
    student = Student.objects.select_for_update().get(pk=student.pk)
    if not can_manage_guardians(actor, student, parent):
        raise PermissionDenied
    guardian, _ = Guardian.objects.get_or_create(user=parent)
    first = not student.guardian_links.exists()
    if make_primary and not first:
        student.guardian_links.filter(is_primary=True).update(is_primary=False)
    link = StudentGuardian.objects.create(
        student=student,
        guardian=guardian,
        relationship=relationship,
        is_primary=first or make_primary,
    )
    audit(
        actor,
        student.user.branch,
        "guardian.linked",
        link,
        {"relationship": relationship, "primary": link.is_primary},
    )
    return link


@transaction.atomic
def add_guardian_account(actor, parent, password, student, relationship, make_primary=False):
    """Create a parent's login and link it to a student, together or not at all."""
    parent.role = parent.Role.PARENT
    parent.branch = student.user.branch
    create_account(actor, parent, password)
    return link_guardian(actor, student, parent, relationship, make_primary)


@transaction.atomic
def make_primary_guardian(actor, link):
    """Make this guardian the student's primary contact; the previous one stays linked."""
    student = Student.objects.select_for_update().get(pk=link.student_id)
    if not can_manage_guardians(actor, student, link.guardian.user):
        raise PermissionDenied
    student.guardian_links.filter(is_primary=True).exclude(pk=link.pk).update(is_primary=False)
    StudentGuardian.objects.filter(pk=link.pk).update(is_primary=True)
    link.refresh_from_db()
    audit(actor, student.user.branch, "guardian.made_primary", link)
    return link


# CSV import --------------------------------------------------------------------------------


def _row_messages(exc):
    """A row's problems as readable text, naming the column where Django names the field."""
    if isinstance(exc, IntegrityError):
        return ["This student or account already exists."]
    if hasattr(exc, "error_dict"):
        return [
            message if field == "__all__" else f"{field.replace('_', ' ')}: {message}"
            for field, messages in exc.message_dict.items()
            for message in messages
        ]
    return exc.messages


def _row_problems(row, branch, classes):
    """Everything wrong with a row's own columns, all at once, so the preview lists every problem
    of the row, not just the first. Checks needing the database (a taken email, a completed
    register on the joining date) come from the services afterwards."""
    problems = []
    if row["classroom"].casefold() not in classes:
        problems.append(
            f"No class “{row['classroom']}” in {branch.name} that year. "
            "Write the grade and section as the school does, e.g. “Class 9-A”."
        )
    try:
        date.fromisoformat(row["joined_on"])
    except ValueError:
        problems.append("joined on: write the date as YYYY-MM-DD, e.g. 2026-06-01.")
    for column in ("admission_number", "first_name", "email"):
        if not row[column]:
            problems.append(f"{column.replace('_', ' ')}: this column can't be empty.")
    for column in ("email", "guardian_email"):
        if row[column]:
            try:
                validate_email(row[column])
            except ValidationError:
                problems.append(
                    f"{column.replace('_', ' ')}: “{row[column]}” isn't an email address."
                )
    guardian_columns = [row[f"guardian_{part}"] for part in ("first_name", "last_name", "phone")]
    if not row["guardian_email"] and (any(guardian_columns) or row["relationship"]):
        problems.append("Give the guardian's email, or leave all guardian columns empty.")
    if (
        row["relationship"]
        and row["relationship"].lower() not in StudentGuardian.Relationship.values
    ):
        problems.append("relationship: use mother, father or guardian.")
    return problems


def _import_row(actor, branch, row, classes):
    """Admit one student (and add or link their guardian) through the ordinary services.
    Returns the usernames of the accounts it created."""
    if problems := _row_problems(row, branch, classes):
        raise ValidationError(problems)
    classroom = classes[row["classroom"].casefold()]
    student_user = User(
        username=row["admission_number"].lower(),
        email=row["email"],
        first_name=row["first_name"],
        last_name=row["last_name"],
        phone=row["phone"],
        role=User.Role.STUDENT,
        branch=branch,
    )
    # A strong password nobody knows: the person sets their own from the emailed link.
    student = admit_student(
        actor,
        student_user,
        secrets.token_urlsafe(24),
        row["admission_number"],
        classroom,
        date.fromisoformat(row["joined_on"]),
    )
    created = [student_user.username]
    if not row["guardian_email"]:
        return created
    relationship = (row["relationship"] or StudentGuardian.Relationship.GUARDIAN).lower()
    parent = User.objects.filter(email__iexact=row["guardian_email"]).first()
    if parent:
        # A parent already known (a brother or sister, or an earlier row): link, don't create.
        if not parent.is_parent or parent.branch_id != branch.pk:
            raise ValidationError(
                f"{row['guardian_email']} belongs to an account that isn't a parent in {branch.name}."
            )
        link_guardian(actor, student, parent, relationship)
        return created
    parent = User(
        username=row["guardian_email"].lower(),
        email=row["guardian_email"],
        first_name=row["guardian_first_name"],
        last_name=row["guardian_last_name"],
        phone=row["guardian_phone"],
    )
    add_guardian_account(actor, parent, secrets.token_urlsafe(24), student, relationship)
    return [*created, parent.username]


def _run_rows(actor, branch, year, rows):
    """Every row through _import_row, each in its own savepoint. Returns ({row number:
    [problems]}, [usernames created]). Row numbers count the header as row 1, as a spreadsheet
    shows them."""
    classes = {
        f"{c.grade.name}-{c.section}".casefold(): c
        for c in Classroom.objects.filter(branch=branch, year=year).select_related("grade")
    }
    errors, created = {}, []
    for number, row in enumerate(rows, start=2):
        try:
            with transaction.atomic():
                created += _import_row(actor, branch, row, classes)
        except (ValidationError, IntegrityError) as exc:
            errors[str(number)] = _row_messages(exc)
    return errors, created


def check_import(actor, branch, year, filename, rows):
    """Check every row exactly as importing would, then undo it all: a dry run. Rows refer to
    each other as a real import would (a family's second child links to the parent created by
    an earlier row). Returns the batch to preview; nothing but the batch is saved."""
    if not can_import(actor, branch):
        raise PermissionDenied
    with transaction.atomic():
        errors, _ = _run_rows(actor, branch, year, rows)
        transaction.set_rollback(True)  # a dry run: every account and enrollment is undone
    batch = ImportBatch.objects.create(
        branch=branch,
        year=year,
        filename=filename[:200],
        rows=rows,
        errors=errors,
        created_by=actor,
    )
    audit(
        actor,
        branch,
        "students.import.checked",
        batch,
        {"rows": len(rows), "rows_with_problems": len(errors)},
    )
    return batch


@transaction.atomic
def confirm_import(actor, batch):
    """Import a checked batch: every row in one transaction, or none.

    The batch row is locked, so a double click imports once; an imported batch is left alone.
    If something changed since the preview (an email taken meanwhile, say), nothing is saved and
    the batch shows the new problems. New accounts get a "set your password" email after commit.
    """
    batch = (
        ImportBatch.objects.select_for_update().select_related("branch", "year").get(pk=batch.pk)
    )
    if not can_import(actor, batch.branch):
        raise PermissionDenied
    if batch.status == ImportBatch.Status.IMPORTED:
        return batch
    if batch.errors:
        raise ValidationError("Fix the problems in the file and upload it again.")
    savepoint = transaction.savepoint()
    errors, created = _run_rows(actor, batch.branch, batch.year, batch.rows)
    if errors:
        transaction.savepoint_rollback(savepoint)  # none of the rows, but keep the new problems
        batch.errors = errors
        batch.save(update_fields=["errors"])
        return batch
    transaction.savepoint_commit(savepoint)
    batch.status = ImportBatch.Status.IMPORTED
    batch.imported_at = timezone.now()
    batch.accounts = created
    batch.save(update_fields=["status", "imported_at", "accounts"])
    audit(
        actor,
        batch.branch,
        "students.imported",
        batch,
        {"students": len(batch.rows), "accounts_created": len(created)},
    )
    run_after_commit(send_import_invites, batch.pk)
    return batch


# Year-end promotion ----------------------------------------------------------------------------

PROMOTE, REPEAT, LEAVE = "promote", "repeat", "leave"
DECISIONS = {PROMOTE: "Moves up", REPEAT: "Repeats the grade", LEAVE: "Leaves the school"}


def year_end_roster(classroom):
    """The class at the end of its year: enrollments not closed before the year ended."""
    year_end = classroom.year.ends_on
    return (
        classroom.enrollments.filter(Q(left_on__isnull=True) | Q(left_on__gte=year_end))
        .select_related("student__user")
        .order_by("student__user__first_name", "student__admission_number")
    )


def promotion_preview(source):
    """Each student of `source` with the default decision (moves up, or leaves after the last
    grade) and whether they are already enrolled in a later year (then they are skipped)."""
    last_grade = source.grade.next_grade() is None
    moved = set(
        Enrollment.objects.filter(
            year__starts_on__gt=source.year.ends_on,
            student__in=source.enrollments.values("student"),
        ).values_list("student_id", flat=True)
    )
    return [
        {
            "enrollment": enrollment,
            "default": LEAVE if last_grade else PROMOTE,
            "already_moved": enrollment.student_id in moved,
        }
        for enrollment in year_end_roster(source)
    ]


def _check_targets(source, target, repeat):
    for classroom in (target, repeat):
        if classroom is None:
            continue
        if classroom.branch_id != source.branch_id:
            raise ValidationError("Choose classes of the same branch.")
        if classroom.year.starts_on <= source.year.ends_on:
            raise ValidationError(f"Choose a class of a year that starts after {source.year.name}.")
    if target and target.grade.order <= source.grade.order:
        raise ValidationError(f"Students move up: choose a grade above {source.grade.name}.")
    if repeat and repeat.grade_id != source.grade_id:
        raise ValidationError(f"Students who repeat need a {source.grade.name} class.")
    if target and repeat and repeat.year_id != target.year_id:
        raise ValidationError("Moving up and repeating are both into the same new year.")


@transaction.atomic
def promote_class(actor, source, decisions, target=None, repeat=None):
    """Move a class on at the end of its year: each student moves up into `target`, repeats in
    `repeat` (the same grade next year), or leaves. `target` is needed only if someone moves up,
    `repeat` only if someone repeats (after the last grade everyone leaves: neither is needed).

    `decisions` maps enrollment id to "promote", "repeat" or "leave", and must cover every
    student not yet moved: nothing happens to a whole class by default (the preview suggests a
    decision for each, which the page pre-selects). All in one transaction with the classes
    locked: every old enrollment closes on the last day of the year and the new ones start on
    the first day of the next. Safe to run again: a student already enrolled in a later year is
    skipped. Returns how many students took each path.
    """
    if not can_promote(actor, source):
        raise PermissionDenied
    ids = sorted({c.pk for c in (source, target, repeat) if c is not None})
    locked = {
        c.pk: c
        for c in Classroom.objects.select_for_update()
        .filter(pk__in=ids)
        .select_related("year", "grade", "branch")
    }
    source = locked[source.pk]
    target = locked[target.pk] if target else None
    repeat = locked[repeat.pk] if repeat else None
    _check_targets(source, target, repeat)
    preview = promotion_preview(source)
    unknown = set(decisions) - {entry["enrollment"].pk for entry in preview}
    if unknown or any(choice not in DECISIONS for choice in decisions.values()):
        raise ValidationError(
            "Each decision must be for a student of this class: promote, repeat or leave."
        )
    last_grade = source.grade.next_grade() is None
    counts = dict.fromkeys([*DECISIONS, "already_moved"], 0)
    for entry in preview:
        enrollment = entry["enrollment"]
        if entry["already_moved"]:
            counts["already_moved"] += 1
            continue
        choice = decisions.get(enrollment.pk)
        if choice is None:
            name = enrollment.student.user.display_name
            raise ValidationError(f"Choose what happens to every student: {name} has no decision.")
        if choice == PROMOTE and last_grade:
            raise ValidationError(
                f"{source.grade.name} is the last grade: students leave or repeat."
            )
        if choice == PROMOTE and target is None:
            raise ValidationError("Choose the class the students move up to.")
        if choice == REPEAT and repeat is None:
            raise ValidationError("Choose a class for the students who repeat.")
        if enrollment.left_on is None:
            enrollment.left_on = source.year.ends_on
            enrollment.save(update_fields=["left_on"])
        if choice != LEAVE:
            classroom = target if choice == PROMOTE else repeat
            Enrollment.objects.create(
                student=enrollment.student,
                classroom=classroom,
                year=classroom.year,
                joined_on=classroom.year.starts_on,
            )
        counts[choice] += 1
    audit(
        actor,
        source.branch,
        "students.promoted",
        f"{source.grade.name}-{source.section} {source.year.name}",
        {
            **counts,
            "to": f"{target.grade.name}-{target.section} {target.year.name}" if target else None,
            "repeat_in": f"{repeat.grade.name}-{repeat.section}" if repeat else None,
        },
    )
    return counts


# Leaving and access ----------------------------------------------------------------------------
#
# A student's sign-in works while they are enrolled (now or later). A parent's works while any of
# their children is enrolled, and then for a grace period so the family can download records and
# pay what is owed: LEAVER_GRACE_DAYS, or LEAVER_FEES_GRACE_DAYS while an invoice is unpaid (never
# indefinitely; after that, fees are settled at the school office). Nothing is deleted; the daily
# review below switches accounts off and back on, revoking sessions and API tokens when it
# switches off. docs/adr/0013-leaving-and-access.md

LEFT_SCHOOL, CHILDREN_LEFT = "left_school", "children_left"
# Invoice statuses with money still owed. fees sits above students, so its model isn't imported:
# invoices are reached through the student's reverse relation.
OWED = ("issued", "partly_paid")


@transaction.atomic
def record_leaving(actor, enrollment, left_on, reason):
    """Record that a student left their class on `left_on` (the last day they attended).

    Refused before the joining date, after the year's end, or before a day on which their
    attendance was already recorded. Their sign-in stops the next day (review_access).
    """
    enrollment = (
        Enrollment.objects.select_for_update()
        .select_related("classroom__year", "student__user")
        .get(pk=enrollment.pk)
    )
    if not can_enroll(actor, enrollment.classroom):
        raise PermissionDenied
    if not reason.strip():
        raise ValidationError({"reason": "Give the reason the student is leaving."})
    if not enrollment.joined_on <= left_on <= enrollment.classroom.year.ends_on:
        raise ValidationError(
            {
                "left_on": f"Choose a day from {enrollment.joined_on:%d %b %Y} to the end of the year."
            }
        )
    # attendance sits above students: its records are reached through the enrollment.
    last_recorded = (
        enrollment.attendance.order_by("-session__date")
        .values_list("session__date", flat=True)
        .first()
    )
    if last_recorded and left_on < last_recorded:
        raise ValidationError(
            {
                "left_on": f"Attendance is recorded for this student on {last_recorded:%d %b %Y}: choose that day or later."
            }
        )
    before = enrollment.left_on
    enrollment.left_on = left_on
    enrollment.save(update_fields=["left_on"])
    audit(
        actor,
        enrollment.classroom.branch,
        "students.left",
        enrollment.student,
        {
            "left_on": left_on.isoformat(),
            "before": before.isoformat() if before else None,
            "reason": reason,
        },
    )
    return enrollment


def _enrolled(today):
    """Students with an enrollment that hasn't ended: current, or starting later."""
    return Student.objects.filter(
        Q(enrollments__left_on__isnull=True) | Q(enrollments__left_on__gte=today)
    )


def review_access(today=None):
    """The daily access review. Returns how many accounts it switched off and on, and the
    parents told when their access ends.

    - A student account switches off the day after their last enrollment ends, and back on if
      they are enrolled again.
    - A parent account stays on while any child is enrolled. After the last child leaves it
      stays on for LEAVER_GRACE_DAYS (LEAVER_FEES_GRACE_DAYS if fees are owed); the parent is
      emailed the end date, with how to download records and pay. Then it switches off, and back
      on if a child is enrolled again.
    An end date a parent has been told is never brought forward. Accounts an administrator
    switched off are never switched on here, and one an administrator switched back on keeps
    access until its access_ends_on.
    """
    today = today or timezone.localdate()
    enrolled = _enrolled(today)
    owing = Student.objects.filter(invoices__status__in=OWED)
    counts = {
        "students_off": 0,
        "students_on": 0,
        "parents_off": 0,
        "parents_on": 0,
        "parents_told": 0,
    }

    leavers = User.objects.filter(
        role=User.Role.STUDENT, is_active=True, student_profile__enrollments__isnull=False
    ).exclude(access_ends_on__gte=today)
    for user in leavers.exclude(student_profile__in=enrolled).distinct():
        counts["students_off"] += set_access(user, False, LEFT_SCHOOL)
    returning = User.objects.filter(
        role=User.Role.STUDENT,
        is_active=False,
        deactivated_reason=LEFT_SCHOOL,
        student_profile__in=enrolled,
    ).distinct()
    for user in returning:
        counts["students_on"] += set_access(user, True)

    grace = timedelta(days=settings.LEAVER_GRACE_DAYS)
    fees_grace = timedelta(days=settings.LEAVER_FEES_GRACE_DAYS)
    parents = User.objects.filter(
        role=User.Role.PARENT, guardian_profile__child_links__isnull=False
    ).distinct()
    for parent in parents.filter(Q(is_active=True) | Q(deactivated_reason=CHILDREN_LEFT)):
        children = Student.objects.filter(guardian_links__guardian__user=parent)
        if children.filter(pk__in=enrolled).exists():
            if not parent.is_active:
                counts["parents_on"] += set_access(parent, True)
            elif parent.access_ends_on:
                User.objects.filter(pk=parent.pk).update(access_ends_on=None)
            continue
        left = [e.left_on for e in Enrollment.objects.filter(student__in=children) if e.left_on]
        if not left:
            continue  # no child has been enrolled yet
        owes = children.filter(pk__in=owing).exists()
        ends_on = max(
            max(left) + (fees_grace if owes else grace), parent.access_ends_on or date.min
        )
        if today > ends_on:
            counts["parents_off"] += set_access(parent, False, CHILDREN_LEFT)
            continue
        if not parent.is_active:  # an invoice issued after leaving extends a lapsed grace period
            counts["parents_on"] += set_access(parent, True)
        elif parent.access_ends_on == ends_on:
            continue  # already told
        User.objects.filter(pk=parent.pk).update(access_ends_on=ends_on)
        run_after_commit(send_access_ending_notice, parent.pk, owes)
        counts["parents_told"] += 1
    return counts
