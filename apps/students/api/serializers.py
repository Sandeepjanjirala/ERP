from django.utils import timezone
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from apps.academics.api.serializers import AcademicYearSerializer, ClassroomSummarySerializer
from apps.academics.selectors import classrooms
from apps.accounts.api.serializers import AccountCreateFields, PersonSerializer
from apps.core.api.fields import ScopedPrimaryKeyField

from ..models import Enrollment, Student
from ..selectors import students


class EnrollmentSerializer(serializers.ModelSerializer):
    classroom = ClassroomSummarySerializer(read_only=True)
    year = AcademicYearSerializer(read_only=True)

    class Meta:
        model = Enrollment
        fields = ["id", "student", "classroom", "year", "joined_on", "left_on"]


class EnrollmentCreateSerializer(serializers.ModelSerializer):
    """Enroll an existing student. The academic year always comes from the classroom."""

    student = ScopedPrimaryKeyField(students)
    classroom = ScopedPrimaryKeyField(classrooms)

    class Meta:
        model = Enrollment
        fields = ["student", "classroom", "joined_on", "left_on"]


class StudentSerializer(serializers.ModelSerializer):
    user = PersonSerializer(read_only=True)
    enrollments = EnrollmentSerializer(many=True, read_only=True)

    class Meta:
        model = Student
        fields = ["id", "admission_number", "user", "enrollments"]


class AdmissionSerializer(AccountCreateFields):
    """A student's login, admission number and first classroom, created together.

    The student's branch is the classroom's branch. They must change the password at first
    sign-in.
    """

    admission_number = serializers.CharField(
        max_length=30,
        validators=[
            UniqueValidator(
                queryset=Student.objects.all(),
                message="This admission number is already in use.",
            )
        ],
    )
    classroom = ScopedPrimaryKeyField(classrooms)
    joined_on = serializers.DateField(default=timezone.localdate)

    class Meta(AccountCreateFields.Meta):
        fields = [*AccountCreateFields.Meta.fields, "admission_number", "classroom", "joined_on"]
