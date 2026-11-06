import factory

from apps.academics.tests.factories import ClassroomFactory
from apps.accounts.tests.factories import StudentUserFactory
from apps.students.models import Enrollment, Student


class StudentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Student

    user = factory.SubFactory(StudentUserFactory)
    admission_number = factory.Sequence(lambda n: f"ADM-{n:05d}")


class EnrollmentFactory(factory.django.DjangoModelFactory):
    """A student in a classroom since the first day of its year, in the classroom's branch."""

    class Meta:
        model = Enrollment

    classroom = factory.SubFactory(ClassroomFactory)
    # Seen from the user being built: ".." is the student, "..." is this enrollment.
    student = factory.SubFactory(
        StudentFactory, user__branch=factory.SelfAttribute("...classroom.branch")
    )
    year = factory.SelfAttribute("classroom.year")
    joined_on = factory.SelfAttribute("classroom.year.starts_on")
