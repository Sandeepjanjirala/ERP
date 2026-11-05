from django.db.models import Prefetch
from rest_framework import viewsets

from apps.accounts.models import User
from apps.core.api.permissions import role_in

from ..models import Student
from ..selectors import enrollments, students
from .filters import StudentFilter
from .serializers import StudentSerializer


class StudentViewSet(viewsets.ReadOnlyModelViewSet):
    """Students in your scope. `?search=` matches first name, last name or admission number."""

    serializer_class = StudentSerializer
    queryset = Student.objects.none()  # for the schema; get_queryset() is the real scope
    permission_classes = [role_in(*User.STAFF)]
    filterset_class = StudentFilter
    search_fields = ["user__first_name", "user__last_name", "admission_number"]

    def get_queryset(self):
        user = self.request.user
        return (
            students(user)
            .prefetch_related(Prefetch("enrollments", queryset=enrollments(user)))
            .order_by("user__first_name", "admission_number")
        )
