from django.utils import timezone
from rest_framework import serializers

from apps.academics.api.serializers import ClassroomSummarySerializer
from apps.accounts.api.serializers import UserSummarySerializer

from ..models import Attendance


class RegisterQuerySerializer(serializers.Serializer):
    date = serializers.DateField(default=timezone.localdate)


class RegisterStudentSerializer(serializers.Serializer):
    enrollment = serializers.IntegerField()
    student = serializers.IntegerField()
    admission_number = serializers.CharField()
    name = serializers.CharField()
    status = serializers.ChoiceField(choices=Attendance.Status.choices, allow_null=True)


class RegisterSerializer(serializers.Serializer):
    """A class's register for one day. `version` is 0 until the register is first saved."""

    classroom = ClassroomSummarySerializer()
    date = serializers.DateField()
    version = serializers.IntegerField()
    recorded_by = UserSummarySerializer(allow_null=True)
    updated_at = serializers.DateTimeField(allow_null=True)
    can_record = serializers.BooleanField()
    students = RegisterStudentSerializer(many=True)


class RegisterRecordSerializer(serializers.Serializer):
    enrollment = serializers.IntegerField()
    status = serializers.ChoiceField(choices=Attendance.Status.choices)


class RegisterSaveSerializer(serializers.Serializer):
    """Send every student on the register, with the `version` you loaded.

    A correction to a saved register needs a `reason`. If someone saved the register after you
    loaded it, the version has moved on and the save is refused with 409.
    """

    version = serializers.IntegerField(min_value=0)
    reason = serializers.CharField(max_length=250, required=False, allow_blank=True, default="")
    records = RegisterRecordSerializer(many=True, allow_empty=False)

    def validate_records(self, records):
        enrollments = [record["enrollment"] for record in records]
        if len(enrollments) != len(set(enrollments)):
            raise serializers.ValidationError("List each student once.")
        return records
