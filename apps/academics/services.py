from django.core.exceptions import PermissionDenied
from django.db import transaction

from apps.audit.services import audit
from apps.organization.models import Organization

from .policies import GROUP_LEVEL, can_manage_setup


def setup_branch(kind, record):
    """The branch a setup record belongs to; None for group-level records."""
    if kind in GROUP_LEVEL:
        return None
    return getattr(record, "branch", None) or record.classroom.branch


@transaction.atomic
def save_setup_record(actor, kind, record):
    """Save an organisation, branch, academic year, classroom, subject or teacher assignment."""
    branch = setup_branch(kind, record)
    if not can_manage_setup(actor, kind, branch):
        raise PermissionDenied
    if kind == "branch":
        record.organization, _ = Organization.objects.get_or_create(pk=1)
    record.save()
    audit(actor, branch, f"setup.{kind}.saved", record)
    return record


@transaction.atomic
def update_setup_record(actor, kind, record, before, changed_fields):
    """Save edits to a classroom, subject or assignment, recording what changed."""
    branch = setup_branch(kind, record)
    if not can_manage_setup(actor, kind, branch):
        raise PermissionDenied
    record.save()
    audit(
        actor,
        branch,
        f"setup.{kind}.updated",
        record,
        {"before": before, "changed_fields": changed_fields},
    )
    return record
