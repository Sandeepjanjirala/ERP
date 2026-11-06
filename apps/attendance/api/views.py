from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.academics.selectors import classrooms
from apps.accounts.models import User
from apps.core.api.permissions import IsSignedIn, role_in

from ..models import LeaveRequest
from ..policies import can_attend
from ..selectors import daily_register, leave_requests
from ..services import decide_leave, register_date_error, request_leave, save_register
from .serializers import (
    LeaveDecisionSerializer,
    LeaveRequestCreateSerializer,
    LeaveRequestSerializer,
    RegisterQuerySerializer,
    RegisterSaveSerializer,
    RegisterSerializer,
)


class RegisterView(generics.GenericAPIView):
    """A classroom's daily attendance register. `?date=YYYY-MM-DD`, default today."""

    serializer_class = RegisterSerializer
    permission_classes = [role_in(*User.STAFF)]

    def load(self, request, pk):
        classroom = get_object_or_404(classrooms(request.user), pk=pk)
        query = RegisterQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        day = query.validated_data["date"]
        if problem := register_date_error(classroom, day):
            raise ValidationError({"date": [problem]})
        return classroom, day

    def payload(self, request, classroom, day):
        register = daily_register(classroom, day)
        session = register["session"]
        return RegisterSerializer(
            {
                "classroom": classroom,
                "date": day,
                "version": session.version if session else 0,
                "recorded_by": session.recorded_by if session else None,
                "updated_at": session.updated_at if session else None,
                "can_record": can_attend(request.user, classroom),
                "students": [
                    {
                        "enrollment": enrollment.pk,
                        "student": enrollment.student_id,
                        "admission_number": enrollment.student.admission_number,
                        "name": enrollment.student.user.display_name,
                        "status": register["statuses"].get(enrollment.pk),
                        "on_leave": enrollment.pk in register["on_leave"],
                    }
                    for enrollment in register["roster"]
                ],
            }
        ).data

    @extend_schema(parameters=[RegisterQuerySerializer])
    def get(self, request, pk):
        classroom, day = self.load(request, pk)
        return Response(self.payload(request, classroom, day))

    @extend_schema(parameters=[RegisterQuerySerializer], request=RegisterSaveSerializer)
    def put(self, request, pk):
        classroom, day = self.load(request, pk)
        body = RegisterSaveSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        save_register(
            request.user,
            classroom,
            day,
            {r["enrollment"]: r["status"] for r in body.validated_data["records"]},
            body.validated_data["version"],
            body.validated_data["reason"],
        )
        return Response(self.payload(request, classroom, day))


class LeaveRequestViewSet(mixins.CreateModelMixin, viewsets.ReadOnlyModelViewSet):
    """Leave requests for the students you can see. Parents apply; the class teacher decides."""

    queryset = LeaveRequest.objects.none()  # for the schema; get_queryset() is the real scope
    filterset_fields = ["status", "student"]

    def get_queryset(self):
        return leave_requests(self.request.user)

    def get_permissions(self):
        if self.action == "create":
            return [role_in(User.Role.PARENT)()]
        return [IsSignedIn()]

    def get_serializer_class(self):
        if self.action == "create":
            return LeaveRequestCreateSerializer
        if self.action in ("approve", "reject"):
            return LeaveDecisionSerializer
        return LeaveRequestSerializer

    @extend_schema(responses={201: LeaveRequestSerializer})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        leave = request_leave(request.user, LeaveRequest(**serializer.validated_data))
        return Response(LeaveRequestSerializer(leave).data, status=status.HTTP_201_CREATED)

    def decide(self, request, approve):
        leave = self.get_object()
        body = LeaveDecisionSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        leave = decide_leave(request.user, leave, approve, body.validated_data["note"])
        return Response(LeaveRequestSerializer(leave).data)

    @extend_schema(responses=LeaveRequestSerializer)
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        """Class teacher or admin: approve. Recorded absences in those days become Excused."""
        return self.decide(request, approve=True)

    @extend_schema(responses=LeaveRequestSerializer)
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        """Class teacher or admin: don't approve. A `note` saying why is required."""
        return self.decide(request, approve=False)
