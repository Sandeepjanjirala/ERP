from rest_framework import serializers

from apps.academics.api.serializers import (
    ClassroomSummarySerializer,
    SubjectSerializer,
    TermSummarySerializer,
)
from apps.academics.selectors import classrooms, subjects
from apps.accounts.api.serializers import UserSummarySerializer
from apps.core.api.fields import ScopedPrimaryKeyField

from ..models import Exam
from ..policies import exam_actions


class ExamSerializer(serializers.ModelSerializer):
    classroom = ClassroomSummarySerializer(read_only=True)
    subject = SubjectSerializer(read_only=True)
    term = TermSummarySerializer(read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    published_by = UserSummarySerializer(read_only=True)

    class Meta:
        model = Exam
        fields = [
            "id",
            "title",
            "date",
            "term",
            "classroom",
            "subject",
            "max_marks",
            "pass_marks",
            "status",
            "status_label",
            "version",
            "published_by",
            "published_at",
        ]
        read_only_fields = fields


class ExamActionsSerializer(serializers.Serializer):
    can_edit_marks = serializers.BooleanField()
    can_submit = serializers.BooleanField()
    can_publish = serializers.BooleanField()
    can_reopen = serializers.BooleanField()


class ExamDetailSerializer(ExamSerializer):
    """An exam plus what the caller may do to it now, from the same policy as the web buttons."""

    actions = serializers.SerializerMethodField()

    class Meta(ExamSerializer.Meta):
        fields = [*ExamSerializer.Meta.fields, "actions"]
        read_only_fields = fields

    def get_actions(self, exam) -> ExamActionsSerializer:
        return exam_actions(self.context["request"].user, exam)


class ExamCreateSerializer(serializers.ModelSerializer):
    """A new exam always starts as a draft. Teachers may use only their own class and subject."""

    classroom = ScopedPrimaryKeyField(classrooms)
    subject = ScopedPrimaryKeyField(subjects)

    class Meta:
        model = Exam
        fields = ["classroom", "subject", "title", "date", "max_marks", "pass_marks"]
        # Uniqueness and the cross-field rules are checked by the model when the service saves.
        validators = []


class MarkRowSerializer(serializers.Serializer):
    enrollment = serializers.IntegerField()
    student = serializers.IntegerField(read_only=True)
    admission_number = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    score = serializers.DecimalField(
        max_digits=6, decimal_places=2, min_value=0, allow_null=True, required=False
    )
    absent = serializers.BooleanField(default=False)


class MarkSheetSerializer(serializers.Serializer):
    exam = ExamDetailSerializer()
    students = MarkRowSerializer(many=True)


class MarkSheetSaveSerializer(serializers.Serializer):
    """Every student on the class list: a score, absent true, or neither to clear the mark."""

    version = serializers.IntegerField(min_value=1)
    marks = MarkRowSerializer(many=True, allow_empty=False)

    def validate_marks(self, rows):
        enrollments = [row["enrollment"] for row in rows]
        if len(enrollments) != len(set(enrollments)):
            raise serializers.ValidationError("List each student once.")
        return rows


class ExamTransitionSerializer(serializers.Serializer):
    version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=250, required=False, allow_blank=True, default="")
