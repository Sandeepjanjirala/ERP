from rest_framework import serializers

from apps.academics.api.serializers import AcademicYearSerializer, ClassroomSummarySerializer
from apps.accounts.api.serializers import PersonSerializer

from ..models import Enrollment, Student


class EnrollmentSerializer(serializers.ModelSerializer):
    classroom = ClassroomSummarySerializer(read_only=True)
    year = AcademicYearSerializer(read_only=True)

    class Meta:
        model = Enrollment
        fields = ["id", "student", "classroom", "year", "joined_on", "left_on"]


class StudentSerializer(serializers.ModelSerializer):
    user = PersonSerializer(read_only=True)
    enrollments = EnrollmentSerializer(many=True, read_only=True)

    class Meta:
        model = Student
        fields = ["id", "admission_number", "user", "enrollments"]
