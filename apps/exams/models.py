from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q

from apps.academics.models import Classroom, Subject, Term
from apps.core.models import ValidatedModel
from apps.students.models import Enrollment


class Exam(ValidatedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Awaiting approval"
        PUBLISHED = "published", "Published"

    classroom = models.ForeignKey(Classroom, on_delete=models.PROTECT, related_name="exams")
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT)
    title = models.CharField(max_length=80)
    date = models.DateField()
    # Never chosen by a person: always the term the date falls in (set on every save).
    term = models.ForeignKey(Term, on_delete=models.PROTECT, related_name="exams")
    max_marks = models.DecimalField(
        max_digits=6, decimal_places=2, validators=[MinValueValidator(Decimal("1"))]
    )
    pass_marks = models.DecimalField(
        max_digits=6, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    version = models.PositiveIntegerField(default=1)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True
    )
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        # pk breaks ties (titles repeat across classes) so pagination is stable.
        ordering = ["-date", "title", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(max_marks__gte=1, pass_marks__gte=0, pass_marks__lte=F("max_marks")),
                name="valid_exam_marks",
            ),
            models.UniqueConstraint(
                fields=["classroom", "subject", "title", "date"], name="unique_exam"
            ),
        ]

    def clean(self):
        if (
            self.classroom_id
            and self.subject_id
            and self.classroom.branch_id != self.subject.branch_id
        ):
            raise ValidationError("Exam subject and classroom must belong to the same branch.")
        if (
            self.classroom_id
            and self.date
            and not self.classroom.year.starts_on <= self.date <= self.classroom.year.ends_on
        ):
            raise ValidationError("Exam date must fall within the academic year.")
        self.assign_term()

    def assign_term(self):
        """Put the exam in the term its date falls in; a clear error if no term covers it."""
        if not (self.classroom_id and self.date):
            return
        year = self.classroom.year
        term = Term.covering(year, self.date)
        if term is None:
            raise ValidationError(
                {
                    "date": f"No term of {year.name} covers {self.date:%d %b %Y}. "
                    "Choose a date inside a term, or ask the super admin to add or extend one "
                    "in Academic setup."
                }
            )
        self.term = term

    def save(self, *args, **kwargs):
        # Before full_clean, so the required term is already in place.
        self.assign_term()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} · {self.subject.name} · {self.classroom}"


class Mark(ValidatedModel):
    exam = models.ForeignKey(Exam, on_delete=models.PROTECT, related_name="marks")
    enrollment = models.ForeignKey(Enrollment, on_delete=models.PROTECT, related_name="marks")
    score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    absent = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["exam", "enrollment"], name="one_mark_per_exam"),
            models.CheckConstraint(
                condition=(
                    Q(absent=True, score__isnull=True)
                    | Q(absent=False, score__gte=0, score__isnull=False)
                ),
                name="score_or_absent",
            ),
        ]

    def clean(self):
        if (
            self.exam_id
            and self.enrollment_id
            and self.exam.classroom_id != self.enrollment.classroom_id
        ):
            raise ValidationError("The student must be enrolled in the exam classroom.")
        if self.absent and self.score is not None:
            raise ValidationError("Absent students cannot also have a score.")
        if not self.absent and self.score is None:
            raise ValidationError("Enter a score or mark the student absent.")
        if self.score is not None and self.exam_id and self.score > self.exam.max_marks:
            raise ValidationError("Score cannot exceed the exam maximum.")

    @property
    def percentage(self):
        return round((self.score or Decimal(0)) / self.exam.max_marks * 100, 1)

    @property
    def passed(self):
        return not self.absent and self.score >= self.exam.pass_marks
