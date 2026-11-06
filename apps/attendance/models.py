from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from apps.academics.models import Classroom
from apps.core.models import ValidatedModel
from apps.students.models import Enrollment, Student


class AttendanceSession(ValidatedModel):
    classroom = models.ForeignKey(
        Classroom, on_delete=models.PROTECT, related_name="attendance_sessions"
    )
    date = models.DateField()
    version = models.PositiveIntegerField(default=1)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["classroom", "date"], name="one_daily_register")
        ]

    def clean(self):
        if (
            self.classroom_id
            and self.date
            and not self.classroom.year.starts_on <= self.date <= self.classroom.year.ends_on
        ):
            raise ValidationError("Attendance date must fall within the academic year.")


class Attendance(ValidatedModel):
    class Status(models.TextChoices):
        PRESENT = "P", "Present"
        ABSENT = "A", "Absent"
        LATE = "L", "Late"
        EXCUSED = "E", "Excused"

    session = models.ForeignKey(AttendanceSession, on_delete=models.PROTECT, related_name="records")
    enrollment = models.ForeignKey(Enrollment, on_delete=models.PROTECT, related_name="attendance")
    status = models.CharField(max_length=1, choices=Status.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["session", "enrollment"], name="one_attendance_student_day"
            ),
            models.CheckConstraint(
                condition=Q(status__in=["P", "A", "L", "E"]), name="valid_attendance_status"
            ),
        ]

    def clean(self):
        if (
            self.session_id
            and self.enrollment_id
            and self.session.classroom_id != self.enrollment.classroom_id
        ):
            raise ValidationError("Attendance must use the matching classroom enrollment.")


class LeaveRequest(ValidatedModel):
    """A parent asks for days off; the class teacher (or an admin) decides."""

    class Status(models.TextChoices):
        PENDING = "pending", "Waiting for the class teacher"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Not approved"

    MAX_DAYS = 31

    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name="leave_requests")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    starts_on = models.DateField()
    ends_on = models.DateField()
    reason = models.CharField(max_length=500)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=250, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_on__gte=F("starts_on")), name="leave_dates_ordered"
            )
        ]

    def clean(self):
        if self.starts_on and self.ends_on:
            if self.ends_on < self.starts_on:
                raise ValidationError({"ends_on": "The last day can't be before the first day."})
            if (self.ends_on - self.starts_on).days >= self.MAX_DAYS:
                raise ValidationError(
                    {"ends_on": f"A request can cover at most {self.MAX_DAYS} days."}
                )

    def covers(self, day):
        return self.starts_on <= day <= self.ends_on

    def __str__(self):
        return f"{self.student} · {self.starts_on:%d %b}–{self.ends_on:%d %b %Y}"
