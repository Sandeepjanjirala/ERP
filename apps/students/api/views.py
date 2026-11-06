from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import User
from apps.core.api.permissions import role_in

from ..models import Enrollment, Student
from ..selectors import enrollments, guardian_links, students
from ..services import (
    add_guardian_account,
    admit_student,
    enroll,
    link_guardian,
    make_primary_guardian,
)
from .filters import EnrollmentFilter, StudentFilter
from .serializers import (
    AdmissionSerializer,
    EnrollmentCreateSerializer,
    EnrollmentSerializer,
    GuardianAccountSerializer,
    GuardianLinkSerializer,
    LinkGuardianSerializer,
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
        writes = self.action in ("create", "link_guardian", "make_primary") or (
            self.action == "guardians" and self.request.method == "POST"
        )
        return [role_in(*(User.MANAGERS if writes else User.STAFF))()]

    def get_serializer_class(self):
        return {
            "create": AdmissionSerializer,
            "guardians": GuardianAccountSerializer,
            "link_guardian": LinkGuardianSerializer,
            "make_primary": GuardianLinkSerializer,
        }.get(self.action, StudentSerializer)

    def guardian_list(self, student, status_code=status.HTTP_200_OK):
        links = guardian_links(self.request.user).filter(student=student)
        return Response(GuardianLinkSerializer(links, many=True).data, status=status_code)

    @extend_schema(methods=["GET"], request=None, responses=GuardianLinkSerializer(many=True))
    @extend_schema(methods=["POST"], responses={201: GuardianLinkSerializer(many=True)})
    @action(detail=True, methods=["get", "post"])
    def guardians(self, request, pk=None):
        """The student's parents. POST creates a new parent account and links it."""
        student = self.get_object()
        if request.method == "GET":
            return self.guardian_list(student)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        password = data.pop("password")
        relationship, make_primary = data.pop("relationship"), data.pop("make_primary")
        add_guardian_account(
            request.user, User(**data), password, student, relationship, make_primary
        )
        return self.guardian_list(student, status.HTTP_201_CREATED)

    @extend_schema(responses={201: GuardianLinkSerializer(many=True)})
    @action(detail=True, methods=["post"], url_path="guardians/link")
    def link_guardian(self, request, pk=None):
        """Link an existing parent account, e.g. for a brother or sister."""
        student = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        link_guardian(request.user, student, **serializer.validated_data)
        return self.guardian_list(student, status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=GuardianLinkSerializer(many=True))
    @action(detail=True, methods=["post"], url_path=r"guardians/(?P<link_pk>[0-9]+)/make-primary")
    def make_primary(self, request, pk=None, link_pk=None):
        """Make this guardian the student's primary contact."""
        student = self.get_object()
        link = get_object_or_404(guardian_links(request.user), pk=link_pk, student=student)
        make_primary_guardian(request.user, link)
        return self.guardian_list(student)

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
