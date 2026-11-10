import django_filters

from apps.academics.api.filters import scoped_classrooms
from apps.academics.models import AcademicYear
from apps.organization.api.filters import scoped_branches

from ..models import Enrollment, Student


class StudentFilter(django_filters.FilterSet):
    branch = django_filters.ModelChoiceFilter(field_name="user__branch", queryset=scoped_branches)
    classroom = django_filters.ModelChoiceFilter(
        field_name="enrollments__classroom", queryset=scoped_classrooms, distinct=True
    )

    class Meta:
        model = Student
        fields = ["branch", "classroom"]


class EnrollmentFilter(django_filters.FilterSet):
    classroom = django_filters.ModelChoiceFilter(queryset=scoped_classrooms)
    year = django_filters.ModelChoiceFilter(queryset=AcademicYear.objects.all())
    student = django_filters.NumberFilter(field_name="student_id")

    class Meta:
        model = Enrollment
        fields = ["classroom", "year", "student"]
