from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.academics.models import Classroom
from apps.core.models import ValidatedModel
from apps.students.models import Enrollment


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
