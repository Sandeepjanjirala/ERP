from rest_framework import serializers

from apps.accounts.api.serializers import UserSummarySerializer
from apps.organization.api.serializers import BranchSerializer

from ..models import AcademicYear, Classroom, Subject, TeachingAssignment


class AcademicYearSerializer(serializers.ModelSerializer):
    class Meta:
        model = AcademicYear
        fields = ["id", "name", "starts_on", "ends_on"]


class ClassroomSummarySerializer(serializers.ModelSerializer):
    """A classroom inside another record: "9-A", its branch and year by id."""

    label = serializers.SerializerMethodField()

    class Meta:
        model = Classroom
        fields = ["id", "label", "grade", "section", "branch", "year"]

    def get_label(self, classroom) -> str:
        return f"{classroom.grade}-{classroom.section}"


class ClassroomSerializer(ClassroomSummarySerializer):
    branch = BranchSerializer(read_only=True)
    year = AcademicYearSerializer(read_only=True)
    homeroom_teacher = UserSummarySerializer(read_only=True)

    class Meta(ClassroomSummarySerializer.Meta):
        fields = [*ClassroomSummarySerializer.Meta.fields, "homeroom_teacher"]


class SubjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subject
        fields = ["id", "name", "code", "branch"]


class TeachingAssignmentSerializer(serializers.ModelSerializer):
    teacher = UserSummarySerializer(read_only=True)
    classroom = ClassroomSummarySerializer(read_only=True)
    subject = SubjectSerializer(read_only=True)

    class Meta:
        model = TeachingAssignment
        fields = ["id", "teacher", "classroom", "subject"]
