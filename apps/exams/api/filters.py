import django_filters

from apps.academics.api.filters import scoped_classrooms
from apps.academics.models import Subject
from apps.academics.selectors import subjects

from ..models import Exam


def scoped_subjects(request):
    return subjects(request.user) if request else Subject.objects.none()


class ExamFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(choices=Exam.Status.choices)
    classroom = django_filters.ModelChoiceFilter(queryset=scoped_classrooms)
    subject = django_filters.ModelChoiceFilter(queryset=scoped_subjects)
    term = django_filters.NumberFilter()

    class Meta:
        model = Exam
        fields = ["status", "classroom", "subject", "term"]
