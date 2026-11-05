from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from apps.accounts.models import User
from apps.core.models import ValidatedModel
from apps.organization.models import Branch


class AcademicYear(ValidatedModel):
    name = models.CharField(max_length=30, unique=True)
    starts_on = models.DateField()
    ends_on = models.DateField()

    class Meta:
        ordering = ["-starts_on"]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_on__gt=F("starts_on")), name="year_dates_ordered"
            )
        ]

    def __str__(self):
        return self.name


class Classroom(ValidatedModel):
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT)
    year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT)
    grade = models.CharField(max_length=25)
    section = models.CharField(max_length=10)
    homeroom_teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="homerooms",
    )

    class Meta:
        ordering = ["branch__name", "grade", "section"]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "year", "grade", "section"], name="unique_classroom"
            )
        ]

    def clean(self):
        if self.homeroom_teacher_id and (
            self.homeroom_teacher.role != User.Role.TEACHER
            or self.homeroom_teacher.branch_id != self.branch_id
        ):
            raise ValidationError({"homeroom_teacher": "Choose a teacher from this branch."})

    def __str__(self):
        return f"{self.grade}-{self.section} · {self.branch.name} · {self.year.name}"


class Subject(ValidatedModel):
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT)
    name = models.CharField(max_length=60)
    code = models.SlugField(max_length=20)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["branch", "code"], name="subject_branch_code")
        ]

    def __str__(self):
        return f"{self.name} · {self.branch.name}"


class TeachingAssignment(ValidatedModel):
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="teaching"
    )
    classroom = models.ForeignKey(Classroom, on_delete=models.PROTECT, related_name="teaching")
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["classroom", "subject"], name="one_subject_teacher_per_class"
            )
        ]

    def clean(self):
        if (
            self.teacher_id
            and self.classroom_id
            and (
                self.teacher.role != User.Role.TEACHER
                or self.teacher.branch_id != self.classroom.branch_id
            )
        ):
            raise ValidationError("The teacher must belong to the classroom branch.")
        if (
            self.subject_id
            and self.classroom_id
            and self.subject.branch_id != self.classroom.branch_id
        ):
            raise ValidationError("The subject must belong to the classroom branch.")

    def __str__(self):
        return f"{self.teacher.display_name} — {self.subject.name} — {self.classroom}"
