"""Read queries for branches, already limited to what the user may see."""

from django.shortcuts import get_object_or_404

from .models import Branch, Organization


def branches(user):
    return Branch.objects.all() if user.system_admin else Branch.objects.filter(pk=user.branch_id)


def selected_branch(user, value):
    """The branch chosen in a ?branch= filter, if it is one of the user's branches (else 404)."""
    return get_object_or_404(branches(user), pk=value) if value and value.isdigit() else None


def school_name():
    """The school group's name, for letterheads; the default before setup."""
    organization = Organization.objects.filter(pk=1).first()
    return organization.name if organization else Organization().name
