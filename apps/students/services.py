from django.core.exceptions import PermissionDenied
from django.db import transaction

from apps.academics.models import Classroom
from apps.accounts.services import create_account
from apps.audit.services import audit

from .models import Enrollment, Guardian, Student, StudentGuardian
from .policies import can_enroll, can_manage_guardians


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
