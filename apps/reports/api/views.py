import django_filters
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, renderers, viewsets
from rest_framework.response import Response

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.audit.selectors import events
from apps.core.api.permissions import role_in
from apps.core.api.renderers import CSVRenderer, PDFRenderer
from apps.exams.selectors import mark_summary
from apps.organization.selectors import school_name, selected_branch
from apps.students.selectors import students

from ..pdf import render_report_card, report_card_filename
from ..selectors import (
    attendance_trend,
    low_attendance,
    overview,
    published_marks,
    student_report,
    subject_performance,
)
from ..services import export_results_csv
from .serializers import (
    AuditEventSerializer,
    DashboardSerializer,
    PerformanceQuerySerializer,
    PerformanceSerializer,
    StudentReportSerializer,
)


class StudentReportView(generics.GenericAPIView):
    """A student's published results and attendance for one year (default: their latest).

    The same report as the web page. Students may read only their own (see `student_id` in
    /me/); other students' reports are a 404 for them.
    """

    serializer_class = StudentReportSerializer
    permission_classes = [role_in(*User.ACADEMIC)]

    @extend_schema(
        parameters=[OpenApiParameter("year", OpenApiTypes.INT, description="Academic year id")]
    )
    def get(self, request, pk):
        student = get_object_or_404(students(request.user), pk=pk)
        report = student_report(request.user, student, request.query_params.get("year"))
        return Response(self.get_serializer({"student": student, **report}).data)


class DashboardView(generics.GenericAPIView):
    """The staff dashboard: headline numbers, classes with today's register, recent exams.

    `?branch=` narrows it to one branch (404 outside your scope). Students have no dashboard;
    they read their own report (see `student_id` in /me/).
    """

    serializer_class = DashboardSerializer
    permission_classes = [role_in(*User.STAFF)]

    @extend_schema(
        parameters=[OpenApiParameter("branch", OpenApiTypes.INT, description="Branch id")]
    )
    def get(self, request):
        branch = selected_branch(request.user, request.query_params.get("branch"))
        data = {
            **overview(request.user, branch),
            "attendance_trend": attendance_trend(request.user, branch),
            "low_attendance": low_attendance(request.user, branch),
        }
        return Response(self.get_serializer(data).data)


def report_filters(request):
    """The ?branch= (404 outside your scope, as on the web page) and ?year= of a report."""
    return (
        selected_branch(request.user, request.query_params.get("branch")),
        request.query_params.get("year"),
    )


class PerformanceView(generics.GenericAPIView):
    """Published results in your scope: the overall pass rate, and per branch and subject."""

    serializer_class = PerformanceSerializer
    permission_classes = [role_in(*User.STAFF)]

    @extend_schema(parameters=[PerformanceQuerySerializer])
    def get(self, request):
        branch, year = report_filters(request)
        marks = published_marks(request.user, year, branch)
        data = {"summary": mark_summary(marks), "subjects": subject_performance(marks)}
        return Response(self.get_serializer(data).data)


class PerformanceExportView(generics.GenericAPIView):
    """Download the published results as CSV, the same file as the web export. Audited."""

    permission_classes = [role_in(*User.STAFF)]
    renderer_classes = [renderers.JSONRenderer, CSVRenderer]

    @extend_schema(
        parameters=[PerformanceQuerySerializer], responses={(200, "text/csv"): OpenApiTypes.STR}
    )
    def get(self, request):
        branch, year = report_filters(request)
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="published-results.csv"'
        export_results_csv(
            request.user, branch, published_marks(request.user, year, branch), response
        )
        return response


class AuditEventFilter(django_filters.FilterSet):
    action = django_filters.CharFilter(
        lookup_expr="startswith", help_text='For example "exam." or "account.login"'
    )
    actor = django_filters.NumberFilter(field_name="actor_id")

    class Meta:
        model = AuditEvent
        fields = ["action", "actor"]


class ActivityViewSet(viewsets.ReadOnlyModelViewSet):
    """The activity log, newest first: who changed what, with before and after values."""

    queryset = AuditEvent.objects.none()  # for the schema; get_queryset() is the real scope
    serializer_class = AuditEventSerializer
    permission_classes = [role_in(*User.LEADERS)]
    filterset_class = AuditEventFilter
    search_fields = ["target", "actor__username"]
    ordering_fields = ["created_at", "action"]

    def get_queryset(self):
        return events(self.request.user)


class ReportCardView(generics.GenericAPIView):
    """The student's report card for one year as a PDF (default: their latest year)."""

    renderer_classes = [renderers.JSONRenderer, PDFRenderer]
    permission_classes = [role_in(*User.ACADEMIC)]

    @extend_schema(
        parameters=[OpenApiParameter("year", OpenApiTypes.INT, description="Academic year id")],
        responses={(200, "application/pdf"): OpenApiTypes.BINARY},
    )
    def get(self, request, pk):
        student = get_object_or_404(students(request.user), pk=pk)
        report = student_report(request.user, student, request.query_params.get("year"))
        response = HttpResponse(
            render_report_card(student, report, school_name()), content_type="application/pdf"
        )
        filename = report_card_filename(student, report)
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
