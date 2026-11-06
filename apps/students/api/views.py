from django.db.models import Prefetch
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.response import Response

from apps.accounts.models import User
from apps.core.api.permissions import role_in

from ..models import Enrollment, Student
from ..selectors import enrollments, students
from ..services import admit_student, enroll
from .filters import EnrollmentFilter, StudentFilter
from .serializers import (
    AdmissionSerializer,
    EnrollmentCreateSerializer,
    EnrollmentSerializer,
    StudentSerializer,
)


class StudentViewSet(mixins.CreateModelMixin, viewsets.ReadOnlyModelViewSet):
    """Students in your scope. `?search=` matches first name, last name or admission number.

    POST admits a new student: login, profile and first enrollment in one transaction.
    """

    queryset = Student.objects.none()  # for the schema; get_queryset() is the real scope
    filterset_class = StudentFilter
    search_fields = ["user__first_name", "user__last_name", "admission_number"]
    ordering_fields = ["user__first_name", "user__last_name", "admission_number"]

    def get_queryset(self):
        user = self.request.user
        return (
            students(user)
            .prefetch_related(Prefetch("enrollments", queryset=enrollments(user)))
            .order_by("user__first_name", "admission_number")
        )

    def get_permissions(self):
        return [role_in(*(User.MANAGERS if self.action == "create" else User.STAFF))()]

    def get_serializer_class(self):
        return AdmissionSerializer if self.action == "create" else StudentSerializer

    @extend_schema(responses={201: StudentSerializer})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        password, admission_number = data.pop("password"), data.pop("admission_number")
        classroom, joined_on = data.pop("classroom"), data.pop("joined_on")
        # What is left is the login: username, names and email.
        user = User(**data, role=User.Role.STUDENT, branch=classroom.branch)
        student = admit_student(
            request.user, user, password, admission_number, classroom, joined_on
        )
        body = StudentSerializer(self.get_queryset().get(pk=student.pk)).data
        return Response(body, status=status.HTTP_201_CREATED)


class EnrollmentViewSet(mixins.CreateModelMixin, viewsets.ReadOnlyModelViewSet):
    """Which class each student is in, per academic year. Admins enroll existing students."""

    queryset = Enrollment.objects.none()  # for the schema; get_queryset() is the real scope
    filterset_class = EnrollmentFilter

    def get_queryset(self):
        return enrollments(self.request.user).order_by(
            "student__user__first_name", "student__admission_number", "pk"
        )

    def get_permissions(self):
        return [role_in(*(User.MANAGERS if self.action == "create" else User.STAFF))()]

    def get_serializer_class(self):
        return EnrollmentCreateSerializer if self.action == "create" else EnrollmentSerializer

    @extend_schema(responses={201: EnrollmentSerializer})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        enrollment = enroll(request.user, Enrollment(**serializer.validated_data))
        body = EnrollmentSerializer(self.get_queryset().get(pk=enrollment.pk)).data
        return Response(body, status=status.HTTP_201_CREATED)
