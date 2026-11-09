import secrets
from datetime import date

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.academics.models import Classroom
from apps.accounts.models import User
from apps.accounts.services import create_account
from apps.audit.services import audit
from apps.core.jobs import run_after_commit

from .models import Enrollment, Guardian, ImportBatch, Student, StudentGuardian
from .policies import can_enroll, can_import, can_manage_guardians
from .tasks import send_import_invites


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


def _import_row(actor, branch, row, classes):
    """Admit one student (and add or link their guardian) through the ordinary services.
    Returns the usernames of the accounts it created."""
    classroom = classes.get(row["classroom"].casefold())
    if classroom is None:
        raise ValidationError(
            f"No class “{row['classroom']}” in {branch.name} that year. "
            "Write the grade and section as the school does, e.g. “Class 9-A”."
        )
    try:
        joined_on = date.fromisoformat(row["joined_on"])
    except ValueError:
        raise ValidationError("joined on: write the date as YYYY-MM-DD, e.g. 2026-06-01.") from None
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
        joined_on,
    )
    created = [student_user.username]
    guardian_fields = [row[f"guardian_{part}"] for part in ("first_name", "last_name", "phone")]
    if not row["guardian_email"]:
        if any(guardian_fields) or row["relationship"]:
            raise ValidationError("Give the guardian's email, or leave all guardian columns empty.")
        return created
    relationship = (row["relationship"] or StudentGuardian.Relationship.GUARDIAN).lower()
    if relationship not in StudentGuardian.Relationship.values:
        raise ValidationError("relationship: use mother, father or guardian.")
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
