from django.db import transaction

from apps.academics.models import Classroom
from apps.accounts.services import create_account
from apps.audit.services import audit

from .models import Enrollment, Student


@transaction.atomic
def admit_student(actor, user, password, admission_number, classroom, joined_on):
    """Create a student's login, profile and first enrollment together, or none of them."""
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
    Classroom.objects.select_for_update().get(pk=enrollment.classroom_id)
    enrollment.year = enrollment.classroom.year
    enrollment.save()
    audit(actor, enrollment.classroom.branch, "setup.enrollment.saved", enrollment)
    return enrollment
