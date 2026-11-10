import factory

from apps.organization.models import Branch, Organization


class OrganizationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Organization
        django_get_or_create = ("id",)  # there is only ever one organisation

    id = 1
    name = "Test Organisation"


class BranchFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Branch

    organization = factory.SubFactory(OrganizationFactory)
    name = factory.Sequence(lambda n: f"Branch {n}")
    code = factory.Sequence(lambda n: f"branch-{n}")
    city = "Hyderabad"
