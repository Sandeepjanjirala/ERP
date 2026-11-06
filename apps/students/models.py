from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from apps.academics.models import AcademicYear, Classroom
from apps.accounts.models import User
from apps.core.models import ValidatedModel


class Student(ValidatedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="student_profile"
    )
    admission_number = models.CharField(max_length=30, unique=True)

    def clean(self):
        if self.user_id and self.user.role != User.Role.STUDENT:
            raise ValidationError("A student profile requires a student account.")

    def __str__(self):
        return f"{self.user.display_name} ({self.admission_number})"


class Enrollment(ValidatedModel):
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name="enrollments")
    classroom = models.ForeignKey(Classroom, on_delete=models.PROTECT, related_name="enrollments")
    year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT)
    joined_on = models.DateField()
    left_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["student__user__first_name", "student__admission_number"]
        constraints = [
            models.UniqueConstraint(fields=["student", "year"], name="one_enrollment_each_year"),
            models.CheckConstraint(
                condition=Q(left_on__isnull=True) | Q(left_on__gte=F("joined_on")),
                name="enrollment_dates_ordered",
            ),
        ]

    def clean(self):
        if self.classroom_id:
            if self.year_id != self.classroom.year_id:
                raise ValidationError("Academic year must match the classroom.")
            if self.student_id and self.student.user.branch_id != self.classroom.branch_id:
                raise ValidationError("Student and classroom must belong to the same branch.")
            if (
                self.joined_on
                and not self.classroom.year.starts_on
                <= self.joined_on
                <= self.classroom.year.ends_on
            ):
                raise ValidationError("Joining date must fall within the academic year.")
            if self.left_on and self.left_on > self.classroom.year.ends_on:
                raise ValidationError("Leaving date must fall within the academic year.")
            if not self.pk and self.joined_on:
                if (
                    self.classroom.attendance_sessions.filter(date__gte=self.joined_on).exists()
                    or self.classroom.exams.filter(date__gte=self.joined_on)
                    # "draft" is Exam.Status.DRAFT; exams sits above students, so not imported.
                    .exclude(status="draft")
                    .exists()
                ):
                    raise ValidationError(
                        "This joining date would change a completed register or locked exam roster. Use a later joining date; historical roster corrections require a supervised data migration."
                    )

    def __str__(self):
        return f"{self.student} · {self.classroom}"


class Guardian(ValidatedModel):
    """A parent account's family profile. A guardian can have several children at the school."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="guardian_profile"
    )

    def clean(self):
        if self.user_id and self.user.role != User.Role.PARENT:
            raise ValidationError("A guardian profile requires a parent account.")

    def __str__(self):
        return self.user.display_name


class StudentGuardian(ValidatedModel):
    """Which guardians a student has. Exactly one of a student's guardians is the primary one."""

    class Relationship(models.TextChoices):
        MOTHER = "mother", "Mother"
        FATHER = "father", "Father"
        GUARDIAN = "guardian", "Guardian"

    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name="guardian_links")
    guardian = models.ForeignKey(Guardian, on_delete=models.PROTECT, related_name="child_links")
    relationship = models.CharField(max_length=10, choices=Relationship.choices)
    is_primary = models.BooleanField(default=False)

    class Meta:
        ordering = ["-is_primary", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "guardian"], name="guardian_once_per_student"
            ),
            # At most one primary guardian per student; the services make sure there is one.
            models.UniqueConstraint(
                fields=["student"], condition=Q(is_primary=True), name="one_primary_guardian"
            ),
        ]

    def clean(self):
        if (
            self.student_id
            and self.guardian_id
            and self.student.user.branch_id != self.guardian.user.branch_id
        ):
            raise ValidationError("A guardian and their child must belong to the same branch.")

    def __str__(self):
        return f"{self.guardian} · {self.get_relationship_display()} of {self.student}"
