from django.core.exceptions import ValidationError

from apps.core.testing import SchoolTestCase
from apps.organization.models import Organization


class OrganizationTests(SchoolTestCase):
    """The single school group."""

    def test_single_org_enforced(self):
        with self.assertRaises(ValidationError):
            Organization.objects.create(id=2, name="Other")
