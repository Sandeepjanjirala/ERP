from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import User
from apps.core.api.permissions import IsSignedIn, role_in

from ..models import Exam
from ..policies import EXAM_AUTHORS
from ..selectors import exams, mark_sheet
from ..services import create_exam, save_marks, transition_exam
from .filters import ExamFilter
from .serializers import (
    ExamCreateSerializer,
    ExamDetailSerializer,
    ExamSerializer,
    ExamTransitionSerializer,
    MarkSheetSaveSerializer,
    MarkSheetSerializer,
)


class ExamViewSet(mixins.CreateModelMixin, viewsets.ReadOnlyModelViewSet):
    """Exams and the result workflow: Draft -> Submitted (teacher) -> Published (principal).

    Students see only published exams they sat. Each write calls the same service as the web
    page, with the exam's `version`; if someone else changed the exam since you loaded it, the
    request is refused with 409.
    """

    queryset = Exam.objects.none()  # for the schema; get_queryset() is the real scope
    filterset_class = ExamFilter
    search_fields = ["title", "subject__name"]
    ordering_fields = ["date", "title"]

    def get_queryset(self):
        return exams(self.request.user).order_by("-date", "title", "pk")

    def get_serializer_class(self):
        return {
            "list": ExamSerializer,
            "create": ExamCreateSerializer,
            "marks": MarkSheetSerializer,
            "submit": ExamTransitionSerializer,
            "publish": ExamTransitionSerializer,
            "reopen": ExamTransitionSerializer,
        }.get(self.action, ExamDetailSerializer)

    def get_permissions(self):
        if self.action == "create":
            return [role_in(*EXAM_AUTHORS)()]
        if self.action == "marks":  # the whole class's marks: staff only
            return [role_in(*User.STAFF)()]
        return [IsSignedIn()]

    def detail_response(self, exam, status_code=status.HTTP_200_OK):
        exam = self.get_queryset().get(pk=exam.pk)  # a fresh copy after a write
        context = self.get_serializer_context()
        return Response(ExamDetailSerializer(exam, context=context).data, status=status_code)

    @extend_schema(responses={201: ExamDetailSerializer})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        exam = create_exam(request.user, Exam(**serializer.validated_data))
        return self.detail_response(exam, status.HTTP_201_CREATED)

    @extend_schema(methods=["PUT"], request=MarkSheetSaveSerializer)
    @action(detail=True, methods=["get", "put"])
    def marks(self, request, pk=None):
        """The mark sheet. PUT every student's score or absence, with the exam's `version`."""
        exam = self.get_object()
        if request.method == "PUT":
            body = MarkSheetSaveSerializer(data=request.data)
            body.is_valid(raise_exception=True)
            entries = {
                row["enrollment"]: (row.get("score"), row["absent"])
                for row in body.validated_data["marks"]
            }
            save_marks(request.user, exam, entries, body.validated_data["version"])
            exam = self.get_queryset().get(pk=exam.pk)
        sheet = mark_sheet(exam)
        rows = []
        for enrollment in sheet["roster"]:
            mark = sheet["marks"].get(enrollment.pk)
            rows.append(
                {
                    "enrollment": enrollment.pk,
                    "student": enrollment.student_id,
                    "admission_number": enrollment.student.admission_number,
                    "name": enrollment.student.user.display_name,
                    "score": mark.score if mark else None,
                    "absent": mark.absent if mark else False,
                }
            )
        context = self.get_serializer_context()
        return Response(MarkSheetSerializer({"exam": exam, "students": rows}, context=context).data)

    def transition(self, request, name):
        exam = self.get_object()
        body = ExamTransitionSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        transition_exam(
            request.user, exam, name, body.validated_data["version"], body.validated_data["reason"]
        )
        return self.detail_response(exam)

    @extend_schema(responses=ExamDetailSerializer)
    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        """Teacher: send a complete draft to the principal. Marks lock."""
        return self.transition(request, "submit")

    @extend_schema(responses=ExamDetailSerializer)
    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        """Principal: publish submitted results to students."""
        return self.transition(request, "publish")

    @extend_schema(responses=ExamDetailSerializer)
    @action(detail=True, methods=["post"])
    def reopen(self, request, pk=None):
        """Principal: return a submitted or published exam to draft. `reason` is required."""
        return self.transition(request, "reopen")
