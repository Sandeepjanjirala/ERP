import django_filters

from apps.academics.api.filters import scoped_classrooms
from apps.organization.api.filters import scoped_branches

from ..models import Student


class StudentFilter(django_filters.FilterSet):
    branch = django_filters.ModelChoiceFilter(field_name="user__branch", queryset=scoped_branches)
    classroom = django_filters.ModelChoiceFilter(
        field_name="enrollments__classroom", queryset=scoped_classrooms, distinct=True
    )

    class Meta:
        model = Student
        fields = ["branch", "classroom"]
