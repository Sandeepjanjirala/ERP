from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics
from rest_framework.response import Response

from apps.students.selectors import students

from ..selectors import student_report
from .serializers import StudentReportSerializer


class StudentReportView(generics.GenericAPIView):
    """A student's published results and attendance for one year (default: their latest).

    The same report as the web page. Students may read only their own (see `student_id` in
    /me/); other students' reports are a 404 for them.
    """

    serializer_class = StudentReportSerializer

    @extend_schema(
        parameters=[OpenApiParameter("year", OpenApiTypes.INT, description="Academic year id")]
    )
    def get(self, request, pk):
        student = get_object_or_404(students(request.user), pk=pk)
        report = student_report(request.user, student, request.query_params.get("year"))
        return Response(self.get_serializer({"student": student, **report}).data)
