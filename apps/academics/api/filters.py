import django_filters

from apps.organization.api.filters import scoped_branches

from ..models import AcademicYear, Classroom, Grade, Subject, TeachingAssignment
from ..selectors import classrooms


def scoped_classrooms(request):
    return classrooms(request.user) if request else Classroom.objects.none()


class ClassroomFilter(django_filters.FilterSet):
    branch = django_filters.ModelChoiceFilter(queryset=scoped_branches)
    year = django_filters.ModelChoiceFilter(queryset=AcademicYear.objects.all())

    class Meta:
        model = Classroom
        fields = ["branch", "year"]


class GradeFilter(django_filters.FilterSet):
    branch = django_filters.ModelChoiceFilter(queryset=scoped_branches)

    class Meta:
        model = Grade
        fields = ["branch"]


class SubjectFilter(django_filters.FilterSet):
    branch = django_filters.ModelChoiceFilter(queryset=scoped_branches)

    class Meta:
        model = Subject
        fields = ["branch"]


class TeachingAssignmentFilter(django_filters.FilterSet):
    classroom = django_filters.ModelChoiceFilter(queryset=scoped_classrooms)
    teacher = django_filters.NumberFilter(field_name="teacher_id")

    class Meta:
        model = TeachingAssignment
        fields = ["classroom", "teacher"]
