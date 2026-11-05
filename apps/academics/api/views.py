from rest_framework import viewsets

from apps.accounts.models import User
from apps.core.api.permissions import role_in

from ..models import AcademicYear, Classroom, Subject, TeachingAssignment
from ..selectors import assignments, classrooms, subjects
from . import filters
from .serializers import (
    AcademicYearSerializer,
    ClassroomSerializer,
    SubjectSerializer,
    TeachingAssignmentSerializer,
)


class AcademicYearViewSet(viewsets.ReadOnlyModelViewSet):
    """Academic years, newest first."""

    serializer_class = AcademicYearSerializer
    queryset = AcademicYear.objects.order_by("-starts_on", "pk")


class ClassroomViewSet(viewsets.ReadOnlyModelViewSet):
    """Classrooms you can see: your branch, your classes as a teacher, your own as a student."""

    serializer_class = ClassroomSerializer
    queryset = Classroom.objects.none()  # for the schema; get_queryset() is the real scope
    filterset_class = filters.ClassroomFilter

    def get_queryset(self):
        return classrooms(self.request.user).order_by("branch__name", "grade", "section", "pk")


class SubjectViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SubjectSerializer
    queryset = Subject.objects.none()
    filterset_class = filters.SubjectFilter
    permission_classes = [role_in(*User.STAFF)]
    search_fields = ["name", "code"]

    def get_queryset(self):
        return subjects(self.request.user).order_by("name", "pk")


class TeachingAssignmentViewSet(viewsets.ReadOnlyModelViewSet):
    """Who teaches which subject in which class (the academic setup page's list)."""

    serializer_class = TeachingAssignmentSerializer
    queryset = TeachingAssignment.objects.none()
    filterset_class = filters.TeachingAssignmentFilter
    permission_classes = [role_in(*User.LEADERS)]

    def get_queryset(self):
        return assignments(self.request.user).order_by("classroom__grade", "subject__name", "pk")
