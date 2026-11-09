from django.utils import timezone
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from apps.academics.api.serializers import AcademicYearSerializer, ClassroomSummarySerializer
from apps.academics.models import AcademicYear
from apps.academics.selectors import classrooms
from apps.accounts.api.serializers import AccountCreateFields, PersonSerializer
from apps.accounts.selectors import parents
from apps.core.api.fields import ScopedPrimaryKeyField
from apps.organization.selectors import branches

from ..models import Enrollment, ImportBatch, Student, StudentGuardian
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


class GuardianLinkSerializer(serializers.ModelSerializer):
    guardian = PersonSerializer(source="guardian.user", read_only=True)

    class Meta:
        model = StudentGuardian
        fields = ["id", "relationship", "is_primary", "guardian"]


class GuardianAccountSerializer(AccountCreateFields):
    """A new parent login, linked to this student. The branch is the student's branch."""

    relationship = serializers.ChoiceField(choices=StudentGuardian.Relationship.choices)
    make_primary = serializers.BooleanField(default=False)

    class Meta(AccountCreateFields.Meta):
        fields = [*AccountCreateFields.Meta.fields, "relationship", "make_primary"]


class LinkGuardianSerializer(serializers.Serializer):
    """An existing parent account in your branch, e.g. for a brother or sister."""

    parent = ScopedPrimaryKeyField(parents)
    relationship = serializers.ChoiceField(choices=StudentGuardian.Relationship.choices)
    make_primary = serializers.BooleanField(default=False)


class ImportBatchSerializer(serializers.ModelSerializer):
    """A checked CSV. `errors` maps a row number (the header is row 1) to its problems; with
    none, POST .../confirm/ imports every row together."""

    status_label = serializers.CharField(source="get_status_display", read_only=True)
    ready = serializers.BooleanField(read_only=True)

    class Meta:
        model = ImportBatch
        fields = [
            "id",
            "filename",
            "branch",
            "year",
            "status",
            "status_label",
            "ready",
            "rows",
            "errors",
            "accounts",
            "created_at",
            "imported_at",
        ]
        read_only_fields = fields


class ImportUploadSerializer(serializers.Serializer):
    """multipart/form-data: the branch and year of the classes, and the CSV (UTF-8, at most 500
    rows and 2 MB; columns as in the template on the web page)."""

    branch = ScopedPrimaryKeyField(branches)
    year = serializers.PrimaryKeyRelatedField(queryset=AcademicYear.objects.all())
    file = serializers.FileField()


class PromotionRowSerializer(serializers.Serializer):
    enrollment = serializers.IntegerField(source="enrollment.pk")
    student = serializers.IntegerField(source="enrollment.student_id")
    name = serializers.CharField(source="enrollment.student.user.display_name")
    admission_number = serializers.CharField(source="enrollment.student.admission_number")
    default = serializers.CharField(help_text="promote, or leave after the last grade")
    already_moved = serializers.BooleanField(help_text="Already enrolled next year: skipped")


class PromotionSerializer(serializers.Serializer):
    """`decisions` maps every student's enrollment id (GET the preview) to promote, repeat or
    leave. `target` is needed only if someone moves up; `repeat` (next year's class of the same
    grade) only if someone repeats."""

    target = ScopedPrimaryKeyField(classrooms, required=False, allow_null=True)
    repeat = ScopedPrimaryKeyField(classrooms, required=False, allow_null=True)
    decisions = serializers.DictField(
        child=serializers.ChoiceField(choices=["promote", "repeat", "leave"])
    )


class PromotionResultSerializer(serializers.Serializer):
    promote = serializers.IntegerField()
    repeat = serializers.IntegerField()
    leave = serializers.IntegerField()
    already_moved = serializers.IntegerField()
