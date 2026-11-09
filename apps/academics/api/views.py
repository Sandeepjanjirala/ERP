from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import generics, mixins, status, viewsets
from rest_framework.response import Response

from apps.accounts.models import User
from apps.core.api.permissions import IsSignedIn, role_in
from apps.organization.api.serializers import BranchSerializer
from apps.organization.models import Branch, Organization
from apps.organization.selectors import branches

from ..models import AcademicYear, Classroom, Grade, Subject, TeachingAssignment
from ..selectors import assignments, classrooms, grades, subjects
from ..services import save_setup_record, update_setup_record
from . import filters
from .serializers import (
    AcademicYearCreateSerializer,
    AcademicYearSerializer,
    BranchCreateSerializer,
    ClassroomSerializer,
    ClassroomUpdateSerializer,
    ClassroomWriteSerializer,
    GradeSerializer,
    GradeUpdateSerializer,
    GradeWriteSerializer,
    OrganizationSerializer,
    SubjectSerializer,
    SubjectUpdateSerializer,
    SubjectWriteSerializer,
    TeachingAssignmentSerializer,
    TeachingAssignmentUpdateSerializer,
    TeachingAssignmentWriteSerializer,
)


class SetupViewSet(mixins.CreateModelMixin, mixins.UpdateModelMixin, viewsets.ReadOnlyModelViewSet):
    """Read a kind of setup record; managers create (POST) and edit (PATCH) it.

    Writes go through save_setup_record / update_setup_record, which check can_manage_setup
    (group-level records: super admins; branch records: managers of that branch) and write the
    activity log. A subclass names its `setup_kind`, its serializers and who may read it.
    """

    setup_kind = ""
    read_roles = None  # None: any signed-in user
    create_serializer_class = None
    update_serializer_class = None
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_permissions(self):
        if self.action in ("create", "partial_update"):
            return [role_in(*User.MANAGERS)()]
        return [role_in(*self.read_roles)()] if self.read_roles else [IsSignedIn()]

    def get_serializer_class(self):
        if self.action == "create":
            return self.create_serializer_class
        if self.action == "partial_update":
            return self.update_serializer_class
        return self.serializer_class

    def read_response(self, record, status_code=status.HTTP_200_OK):
        record = self.get_queryset().get(pk=record.pk)  # a fresh, fully loaded copy
        data = self.serializer_class(record, context=self.get_serializer_context()).data
        return Response(data, status=status_code)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = self.serializer_class.Meta.model(**serializer.validated_data)
        save_setup_record(request.user, self.setup_kind, record)
        return self.read_response(record, status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        record = self.get_object()
        before = str(record)
        serializer = self.get_serializer(record, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        changed = [
            field
            for field, value in serializer.validated_data.items()
            if getattr(record, field) != value
        ]
        for field, value in serializer.validated_data.items():
            setattr(record, field, value)
        update_setup_record(request.user, self.setup_kind, record, before, changed)
        return self.read_response(record)


@extend_schema_view(create=extend_schema(responses={201: BranchSerializer}))
class BranchViewSet(SetupViewSet):
    """Branches you work in: every branch for a super admin, otherwise your own.

    Served by the academics app because creating a branch writes the activity log, and the
    organization app sits below audit in the layer order.
    """

    setup_kind = "branch"
    serializer_class = BranchSerializer
    create_serializer_class = BranchCreateSerializer
    queryset = Branch.objects.none()  # for the schema; get_queryset() is the real scope
    search_fields = ["name", "code", "city"]
    http_method_names = ["get", "post", "head", "options"]  # no branch edits on the web either

    def get_queryset(self):
        return branches(self.request.user).order_by("name", "pk")


@extend_schema_view(create=extend_schema(responses={201: AcademicYearSerializer}))
class AcademicYearViewSet(SetupViewSet):
    """Academic years, newest first. Super admins add years."""

    setup_kind = "year"
    serializer_class = AcademicYearSerializer
    create_serializer_class = AcademicYearCreateSerializer
    queryset = AcademicYear.objects.order_by("-starts_on", "pk")
    http_method_names = ["get", "post", "head", "options"]


@extend_schema_view(
    create=extend_schema(responses={201: GradeSerializer}),
    partial_update=extend_schema(responses=GradeSerializer),
)
class GradeViewSet(SetupViewSet):
    """The grades each branch teaches, in order (Class 1 is 1). Managers add and rename them."""

    setup_kind = "grade"
    serializer_class = GradeSerializer
    create_serializer_class = GradeWriteSerializer
    update_serializer_class = GradeUpdateSerializer
    queryset = Grade.objects.none()  # for the schema; get_queryset() is the real scope
    filterset_class = filters.GradeFilter

    def get_queryset(self):
        return grades(self.request.user).order_by("branch__name", "order", "pk")


@extend_schema_view(
    create=extend_schema(responses={201: ClassroomSerializer}),
    partial_update=extend_schema(responses=ClassroomSerializer),
)
class ClassroomViewSet(SetupViewSet):
    """Classrooms you can see: your branch, your classes as a teacher, your own as a student."""

    setup_kind = "classroom"
    serializer_class = ClassroomSerializer
    create_serializer_class = ClassroomWriteSerializer
    update_serializer_class = ClassroomUpdateSerializer
    queryset = Classroom.objects.none()  # for the schema; get_queryset() is the real scope
    filterset_class = filters.ClassroomFilter

    def get_queryset(self):
        return classrooms(self.request.user).order_by(
            "branch__name", "grade__order", "section", "pk"
        )


@extend_schema_view(
    create=extend_schema(responses={201: SubjectSerializer}),
    partial_update=extend_schema(responses=SubjectSerializer),
)
class SubjectViewSet(SetupViewSet):
    setup_kind = "subject"
    serializer_class = SubjectSerializer
    create_serializer_class = SubjectWriteSerializer
    update_serializer_class = SubjectUpdateSerializer
    queryset = Subject.objects.none()
    filterset_class = filters.SubjectFilter
    read_roles = User.STAFF
    search_fields = ["name", "code"]

    def get_queryset(self):
        return subjects(self.request.user).order_by("name", "pk")


@extend_schema_view(
    create=extend_schema(responses={201: TeachingAssignmentSerializer}),
    partial_update=extend_schema(responses=TeachingAssignmentSerializer),
)
class TeachingAssignmentViewSet(SetupViewSet):
    """Who teaches which subject in which class (the academic setup page's list)."""

    setup_kind = "assignment"
    serializer_class = TeachingAssignmentSerializer
    create_serializer_class = TeachingAssignmentWriteSerializer
    update_serializer_class = TeachingAssignmentUpdateSerializer
    queryset = TeachingAssignment.objects.none()
    filterset_class = filters.TeachingAssignmentFilter
    read_roles = User.LEADERS

    def get_queryset(self):
        return assignments(self.request.user).order_by(
            "classroom__grade__order", "subject__name", "pk"
        )


class OrganizationView(generics.RetrieveUpdateAPIView):
    """The school group's name. Everyone may read it; super admins rename it (PATCH)."""

    serializer_class = OrganizationSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_permissions(self):
        if self.request.method == "PATCH":
            return [role_in(User.Role.SUPER)()]
        return [IsSignedIn()]

    def get_object(self):
        # There is one organisation (id 1). Before setup it doesn't exist yet: show the default
        # rather than writing on a read; the first PATCH saves it.
        return Organization.objects.filter(pk=1).first() or Organization()

    def partial_update(self, request, *args, **kwargs):
        organization = self.get_object()
        serializer = self.get_serializer(organization, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        organization.name = serializer.validated_data.get("name", organization.name)
        save_setup_record(request.user, "organization", organization)
        return Response(self.get_serializer(organization).data)
