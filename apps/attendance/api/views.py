from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.academics.selectors import classrooms
from apps.accounts.models import User
from apps.core.api.permissions import role_in

from ..policies import can_attend
from ..selectors import daily_register
from ..services import register_date_error, save_register
from .serializers import RegisterQuerySerializer, RegisterSaveSerializer, RegisterSerializer


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
