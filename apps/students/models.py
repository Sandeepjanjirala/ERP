from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from apps.academics.models import AcademicYear, Classroom
from apps.core.models import ValidatedModel


class Student(ValidatedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="student_profile"
    )
    admission_number = models.CharField(max_length=30, unique=True)

    def clean(self):
        if self.user_id and self.user.role != "student":
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
                    .exclude(status="draft")
                    .exists()
                ):
                    raise ValidationError(
                        "This joining date would change a completed register or locked exam roster. Use a later joining date; historical roster corrections require a supervised data migration."
                    )

    def __str__(self):
        return f"{self.student} · {self.classroom}"
