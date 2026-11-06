from decimal import Decimal

import factory
from django.utils import timezone

from apps.academics.tests.factories import ClassroomFactory, SubjectFactory
from apps.exams.models import Exam


class ExamFactory(factory.django.DjangoModelFactory):
    """A draft exam held today, for a subject in the classroom's branch."""

    class Meta:
        model = Exam

    classroom = factory.SubFactory(ClassroomFactory)
    subject = factory.SubFactory(SubjectFactory, branch=factory.SelfAttribute("..classroom.branch"))
    title = factory.Sequence(lambda n: f"Test {n}")
    date = factory.LazyFunction(timezone.localdate)
    max_marks = Decimal("100")
    pass_marks = Decimal("35")
