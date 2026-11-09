from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from apps.academics.models import Classroom
from apps.academics.selectors import classrooms
from apps.accounts.models import User
from apps.core.api.permissions import role_in

from ..imports import read_csv
from ..models import Enrollment, ImportBatch, Student
from ..selectors import enrollments, guardian_links, import_batches, students
from ..services import (
    add_guardian_account,
    admit_student,
    check_import,
    confirm_import,
    enroll,
    link_guardian,
    make_primary_guardian,
    promote_class,
    promotion_preview,
)
from .filters import EnrollmentFilter, StudentFilter
from .serializers import (
    AdmissionSerializer,
    EnrollmentCreateSerializer,
    EnrollmentSerializer,
    GuardianAccountSerializer,
    GuardianLinkSerializer,
    ImportBatchSerializer,
    ImportUploadSerializer,
    LinkGuardianSerializer,
    PromotionResultSerializer,
    PromotionRowSerializer,
    PromotionSerializer,
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


class StudentImportViewSet(mixins.CreateModelMixin, viewsets.ReadOnlyModelViewSet):
    """CSV imports of students. POST a file to check it (nothing is imported); then POST
    /{id}/confirm/ to import every row together, or none."""

    queryset = ImportBatch.objects.none()  # for the schema; get_queryset() is the real scope
    serializer_class = ImportBatchSerializer
    permission_classes = [role_in(*User.MANAGERS)]
    parser_classes = [MultiPartParser]

    def get_queryset(self):
        return import_batches(self.request.user)

    def get_serializer_class(self):
        return ImportUploadSerializer if self.action == "create" else ImportBatchSerializer

    @extend_schema(responses={201: ImportBatchSerializer})
    def create(self, request, *args, **kwargs):
        body = self.get_serializer(data=request.data)
        body.is_valid(raise_exception=True)
        upload = body.validated_data["file"]
        try:
            rows = read_csv(upload)
        except ValidationError as exc:
            raise ValidationError({"file": exc.messages}) from None
        batch = check_import(
            request.user,
            body.validated_data["branch"],
            body.validated_data["year"],
            upload.name,
            rows,
        )
        return Response(ImportBatchSerializer(batch).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=ImportBatchSerializer)
    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        """Import every row together. An already imported batch is returned unchanged; if
        something changed since the check, nothing is imported and `errors` says why."""
        batch = confirm_import(request.user, self.get_object())
        return Response(ImportBatchSerializer(batch).data)


class PromotionView(generics.GenericAPIView):
    """Year-end promotion of a class. GET previews each student; POST moves the class on in one
    transaction (principals and admins of the branch). Running it again changes nothing for
    students already enrolled in a later year."""

    serializer_class = PromotionSerializer
    permission_classes = [role_in(*User.LEADERS)]
    queryset = Classroom.objects.none()  # for the schema; the class comes from classrooms()

    def source(self, request, pk):
        return get_object_or_404(classrooms(request.user), pk=pk)

    @extend_schema(responses=PromotionRowSerializer(many=True))
    def get(self, request, pk):
        rows = promotion_preview(self.source(request, pk))
        return Response(PromotionRowSerializer(rows, many=True).data)

    @extend_schema(responses=PromotionResultSerializer)
    def post(self, request, pk):
        source = self.source(request, pk)
        body = self.get_serializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        decisions = {}
        for key, value in data["decisions"].items():
            if not str(key).isdigit():
                raise ValidationError({"decisions": ["Use enrollment ids as keys."]})
            decisions[int(key)] = value
        counts = promote_class(
            request.user, source, decisions, data.get("target"), data.get("repeat")
        )
        return Response(PromotionResultSerializer(counts).data)
