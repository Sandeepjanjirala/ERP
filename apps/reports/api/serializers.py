from rest_framework import serializers

from apps.academics.api.serializers import AcademicYearSerializer, ClassroomSummarySerializer
from apps.exams.models import Mark
from apps.students.api.serializers import EnrollmentSerializer, StudentSerializer


class ResultSerializer(serializers.ModelSerializer):
    """One published mark, with the exam it belongs to."""

    exam = serializers.IntegerField(source="exam_id")
    exam_title = serializers.CharField(source="exam.title")
    subject = serializers.CharField(source="exam.subject.name")
    classroom = ClassroomSummarySerializer(source="exam.classroom")
    date = serializers.DateField(source="exam.date")
    max_marks = serializers.DecimalField(source="exam.max_marks", max_digits=6, decimal_places=2)
    percentage = serializers.DecimalField(max_digits=5, decimal_places=1)
    passed = serializers.BooleanField()

    class Meta:
        model = Mark
        fields = ["exam", "exam_title", "subject", "classroom", "date", "score", "absent"]
        fields += ["max_marks", "percentage", "passed"]


class MarkSummarySerializer(serializers.Serializer):
    count = serializers.IntegerField()
    earned = serializers.DecimalField(max_digits=10, decimal_places=2)
    possible = serializers.DecimalField(max_digits=10, decimal_places=2)
    percentage = serializers.DecimalField(max_digits=5, decimal_places=1, allow_null=True)
    passed = serializers.IntegerField()


class AttendanceSummarySerializer(serializers.Serializer):
    present = serializers.IntegerField(source="P")
    absent = serializers.IntegerField(source="A")
    late = serializers.IntegerField(source="L")
    excused = serializers.IntegerField(source="E")
    total = serializers.IntegerField()
    rate = serializers.FloatField(allow_null=True, help_text="Present and late, out of days")


class StudentReportSerializer(serializers.Serializer):
    student = StudentSerializer()
    selected_year = AcademicYearSerializer(allow_null=True)
    years = AcademicYearSerializer(many=True)
    enrollments = EnrollmentSerializer(many=True)
    results = ResultSerializer(many=True, source="marks")
    summary = MarkSummarySerializer()
    attendance = AttendanceSummarySerializer(source="attendance_summary")
