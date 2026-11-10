import factory

from apps.accounts.models import User
from apps.core.testing import PASSWORD
from apps.organization.tests.factories import BranchFactory


class UserFactory(factory.django.DjangoModelFactory):
    """A branch account (a teacher by default) that can sign in with PASSWORD straight away."""

    class Meta:
        model = User

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.LazyAttribute(lambda user: f"{user.username}@example.com")
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    password = factory.django.Password(PASSWORD)
    role = User.Role.TEACHER
    branch = factory.SubFactory(BranchFactory)
    must_change_password = False


class TeacherFactory(UserFactory):
    role = User.Role.TEACHER


class StudentUserFactory(UserFactory):
    role = User.Role.STUDENT
