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


class Term(ValidatedModel):
    """A part of an academic year, such as "Term 1". Terms of a year never overlap, and each
    exam belongs to the term its date falls in."""

    year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name="terms")
    name = models.CharField(max_length=30)
    starts_on = models.DateField()
    ends_on = models.DateField()

    class Meta:
        ordering = ["starts_on", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["year", "name"], name="term_name_per_year"),
            models.CheckConstraint(
                condition=Q(ends_on__gte=F("starts_on")), name="term_dates_ordered"
            ),
        ]

    def clean(self):
        if not (self.year_id and self.starts_on and self.ends_on):
            return
        year = self.year
        if not year.starts_on <= self.starts_on <= self.ends_on <= year.ends_on:
            raise ValidationError(
                f"A term must fall within {year.name} "
                f"({year.starts_on:%d %b %Y} to {year.ends_on:%d %b %Y})."
            )
        overlap = (
            Term.objects.filter(year=year, starts_on__lte=self.ends_on, ends_on__gte=self.starts_on)
            .exclude(pk=self.pk)
            .first()
        )
        if overlap:
            raise ValidationError(f"Terms can't overlap: {overlap.name} covers some of these days.")

    @staticmethod
    def covering(year, day):
        """The term of `year` that `day` falls in, or None."""
        return Term.objects.filter(year=year, starts_on__lte=day, ends_on__gte=day).first()

    def __str__(self):
        return f"{self.name} · {self.year.name}"


class Grade(ValidatedModel):
    """A level of study in a branch, such as "Class 9". `order` puts grades in sequence, so
    year-end promotion knows which grade comes next."""

    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="grades")
    name = models.CharField(max_length=25)
    order = models.PositiveSmallIntegerField(
        help_text="Position in the school, lowest first: Class 1 is 1, Class 10 is 10."
    )

    class Meta:
        ordering = ["order", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["branch", "name"], name="grade_name_per_branch"),
            models.UniqueConstraint(fields=["branch", "order"], name="grade_order_per_branch"),
        ]

    def next_grade(self):
        """The grade students move up to, or None for the last grade (they leave the school)."""
        return (
            Grade.objects.filter(branch_id=self.branch_id, order__gt=self.order)
            .order_by("order")
            .first()
        )

    def __str__(self):
        return self.name


class Classroom(ValidatedModel):
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT)
    year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT)
    grade = models.ForeignKey(Grade, on_delete=models.PROTECT, related_name="classrooms")
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
        if self.grade_id and self.branch_id and self.grade.branch_id != self.branch_id:
            raise ValidationError({"grade": "Choose a grade of this branch."})
        if self.homeroom_teacher_id and (
            self.homeroom_teacher.role != User.Role.TEACHER
            or self.homeroom_teacher.branch_id != self.branch_id
        ):
            raise ValidationError({"homeroom_teacher": "Choose a teacher from this branch."})

    def __str__(self):
        return f"{self.grade}-{self.section} · {self.branch.name} · {self.year.name}"


class Period(ValidatedModel):
    """A lesson slot in a branch's school day (its bell schedule), such as period 1, 08:30-09:15.
    Every class in the branch uses the same periods."""

    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="periods")
    number = models.PositiveSmallIntegerField()
    starts_at = models.TimeField()
    ends_at = models.TimeField()

    class Meta:
        ordering = ["number", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["branch", "number"], name="period_number_per_branch"),
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")), name="period_times_ordered"
            ),
        ]

    def __str__(self):
        return f"Period {self.number} ({self.starts_at:%H:%M}-{self.ends_at:%H:%M})"

    def clean(self):
        if not (self.branch_id and self.starts_at and self.ends_at):
            return
        overlap = (
            Period.objects.filter(
                branch_id=self.branch_id, starts_at__lt=self.ends_at, ends_at__gt=self.starts_at
            )
            .exclude(pk=self.pk)
            .first()
        )
        if overlap:
            raise ValidationError(f"Periods can't overlap: {overlap} covers some of this time.")


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


class TimetableSlot(ValidatedModel):
    """One lesson in a class's weekly timetable: a weekday, a period, and who teaches what.

    The database refuses a class booked twice in one period, and a teacher booked twice in one
    period of the same year. `year` is copied from the classroom so the second rule can be a
    database constraint.
    """

    class Day(models.IntegerChoices):
        MONDAY = 1, "Monday"
        TUESDAY = 2, "Tuesday"
        WEDNESDAY = 3, "Wednesday"
        THURSDAY = 4, "Thursday"
        FRIDAY = 5, "Friday"
        SATURDAY = 6, "Saturday"

    classroom = models.ForeignKey(Classroom, on_delete=models.PROTECT, related_name="timetable")
    year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name="+")
    weekday = models.PositiveSmallIntegerField(choices=Day.choices)
    period = models.ForeignKey(Period, on_delete=models.PROTECT, related_name="slots")
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="+")
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="lessons"
    )

    class Meta:
        ordering = ["weekday", "period__number", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["classroom", "weekday", "period"], name="class_once_per_period"
            ),
            models.UniqueConstraint(
                fields=["teacher", "year", "weekday", "period"], name="teacher_once_per_period"
            ),
        ]

    def __str__(self):
        return f"{self.get_weekday_display()} {self.period}: {self.subject.name}, {self.classroom}"

    def clean(self):
        if self.classroom_id:
            self.year_id = self.classroom.year_id
        if (
            self.classroom_id
            and self.period_id
            and self.period.branch_id != self.classroom.branch_id
        ):
            raise ValidationError("Choose a period of the classroom's branch.")
        if (
            self.classroom_id
            and self.subject_id
            and self.teacher_id
            and not TeachingAssignment.objects.filter(
                classroom_id=self.classroom_id,
                subject_id=self.subject_id,
                teacher_id=self.teacher_id,
            ).exists()
        ):
            raise ValidationError("Only a teacher assigned to this class and subject can teach it.")

    def save(self, *args, **kwargs):
        if self.classroom_id:
            self.year_id = self.classroom.year_id  # before full_clean, which needs it
        return super().save(*args, **kwargs)
