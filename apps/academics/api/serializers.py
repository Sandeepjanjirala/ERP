from rest_framework import serializers

from apps.accounts.api.serializers import UserSummarySerializer
from apps.accounts.selectors import teachers
from apps.core.api.fields import ScopedPrimaryKeyField
from apps.organization.api.serializers import BranchSerializer
from apps.organization.models import Branch, Organization
from apps.organization.selectors import branches

from ..models import AcademicYear, Classroom, Subject, TeachingAssignment
from ..selectors import classrooms, subjects


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


# Writes. Every id must come from the caller's scope; uniqueness and the cross-branch rules are
# checked by the model when the service saves (validators = [] avoids checking them twice).


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ["id", "name"]
        read_only_fields = ["id"]


class BranchCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = ["name", "code", "city"]
        validators = []


class AcademicYearCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = AcademicYear
        fields = ["name", "starts_on", "ends_on"]
        validators = []


class ClassroomWriteSerializer(serializers.ModelSerializer):
    """Branch and year are fixed once the classroom exists; PATCH changes the rest."""

    branch = ScopedPrimaryKeyField(branches)
    year = serializers.PrimaryKeyRelatedField(queryset=AcademicYear.objects.all())
    homeroom_teacher = ScopedPrimaryKeyField(teachers, allow_null=True, required=False)

    class Meta:
        model = Classroom
        fields = ["branch", "year", "grade", "section", "homeroom_teacher"]
        validators = []


class ClassroomUpdateSerializer(ClassroomWriteSerializer):
    # Redeclared: Meta.read_only_fields does not apply to fields declared on the parent class.
    branch = serializers.PrimaryKeyRelatedField(read_only=True)
    year = serializers.PrimaryKeyRelatedField(read_only=True)


class SubjectWriteSerializer(serializers.ModelSerializer):
    branch = ScopedPrimaryKeyField(branches)

    class Meta:
        model = Subject
        fields = ["branch", "name", "code"]
        validators = []


class SubjectUpdateSerializer(SubjectWriteSerializer):
    branch = serializers.PrimaryKeyRelatedField(read_only=True)


class TeachingAssignmentWriteSerializer(serializers.ModelSerializer):
    """Classroom and subject are fixed once assigned; PATCH changes the teacher."""

    teacher = ScopedPrimaryKeyField(teachers)
    classroom = ScopedPrimaryKeyField(classrooms)
    subject = ScopedPrimaryKeyField(subjects)

    class Meta:
        model = TeachingAssignment
        fields = ["teacher", "classroom", "subject"]
        validators = []


class TeachingAssignmentUpdateSerializer(TeachingAssignmentWriteSerializer):
    classroom = serializers.PrimaryKeyRelatedField(read_only=True)
    subject = serializers.PrimaryKeyRelatedField(read_only=True)
