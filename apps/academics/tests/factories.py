from datetime import timedelta

import factory
from django.utils import timezone

from apps.academics.models import AcademicYear, Classroom, Grade, Subject, TeachingAssignment
from apps.accounts.tests.factories import TeacherFactory
from apps.organization.tests.factories import BranchFactory


class AcademicYearFactory(factory.django.DjangoModelFactory):
    """A year that is under way: it started 90 days ago."""

    class Meta:
        model = AcademicYear

    name = factory.Sequence(lambda n: f"Year {n}")
    starts_on = factory.LazyFunction(lambda: timezone.localdate() - timedelta(days=90))
    ends_on = factory.LazyAttribute(lambda year: year.starts_on + timedelta(days=300))


class GradeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Grade

    branch = factory.SubFactory(BranchFactory)
    name = factory.Sequence(lambda n: f"Grade {n}")
    order = factory.Sequence(lambda n: n + 1)


class ClassroomFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Classroom

    branch = factory.SubFactory(BranchFactory)
    year = factory.SubFactory(AcademicYearFactory)
    grade = factory.SubFactory(GradeFactory, branch=factory.SelfAttribute("..branch"))
    section = factory.Sequence(lambda n: f"S{n}")
    # The homeroom teacher must work in the classroom's branch.
    homeroom_teacher = factory.SubFactory(TeacherFactory, branch=factory.SelfAttribute("..branch"))


class SubjectFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Subject

    branch = factory.SubFactory(BranchFactory)
    name = factory.Sequence(lambda n: f"Subject {n}")
    code = factory.Sequence(lambda n: f"subject-{n}")


class TeachingAssignmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TeachingAssignment

    classroom = factory.SubFactory(ClassroomFactory)
    subject = factory.SubFactory(SubjectFactory, branch=factory.SelfAttribute("..classroom.branch"))
    teacher = factory.SubFactory(TeacherFactory, branch=factory.SelfAttribute("..classroom.branch"))
