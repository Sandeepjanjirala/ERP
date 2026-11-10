from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.academics.models import Classroom
from apps.core.models import ValidatedModel
from apps.organization.models import Branch


class Announcement(ValidatedModel):
    class Audience(models.TextChoices):
        EVERYONE = "everyone", "Everyone"
        STAFF = "staff", "Staff"
        STUDENTS = "students", "Students"
        PARENTS = "parents", "Parents"
        CLASS = "class", "One class (its students and parents)"

    # No branch: every branch of the school group (super admins only).
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, null=True, blank=True)
    audience = models.CharField(max_length=10, choices=Audience.choices)
    classroom = models.ForeignKey(Classroom, on_delete=models.PROTECT, null=True, blank=True)
    title = models.CharField(max_length=120)
    body = models.TextField(max_length=4000)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(audience="class", classroom__isnull=False)
                    | (~Q(audience="class") & Q(classroom__isnull=True))
                ),
                name="classroom_only_for_class_audience",
            )
        ]

    def clean(self):
        if self.audience == self.Audience.CLASS and not self.classroom_id:
            raise ValidationError({"classroom": "Choose the class this announcement is for."})
        if self.audience != self.Audience.CLASS and self.classroom_id:
            raise ValidationError({"classroom": "A class is only chosen for a class announcement."})
        if self.classroom_id and self.classroom.branch_id != self.branch_id:
            raise ValidationError({"classroom": "Choose a class in this branch."})

    def __str__(self):
        return self.title


class Notification(models.Model):
    """One message in one person's notification bell. Written only by communication.services."""

    class Kind(models.TextChoices):
        ANNOUNCEMENT = "announcement", "Announcement"
        ABSENCE = "absence", "Absence"
        RESULTS = "results", "Results"
        LEAVE = "leave", "Leave request"
        FEES = "fees", "Fees"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    kind = models.CharField(max_length=15, choices=Kind.choices)
    # What this notification is about, e.g. "announcement:12". Unique per recipient, so a job
    # that runs twice can't notify (or email) anyone twice.
    key = models.CharField(max_length=80)
    title = models.CharField(max_length=160)
    body = models.CharField(max_length=500, blank=True)
    url = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["recipient", "key"], name="one_notification_per_event")
        ]
        indexes = [models.Index(fields=["recipient", "read_at"], name="unread_by_recipient")]

    def __str__(self):
        return self.title
