from django.db import transaction

from apps.audit.services import audit
from apps.organization.models import Organization


@transaction.atomic
def save_setup_record(actor, kind, record):
    """Save an organisation, branch, academic year, classroom, subject or teacher assignment."""
    if kind == "branch":
        record.organization, _ = Organization.objects.get_or_create(pk=1)
    record.save()
    branch = getattr(record, "branch", None) or getattr(
        getattr(record, "classroom", None), "branch", None
    )
    audit(actor, branch, f"setup.{kind}.saved", record)
    return record


@transaction.atomic
def update_setup_record(actor, kind, record, before, changed_fields):
    """Save edits to a classroom, subject or assignment, recording what changed."""
    record.save()
    branch = getattr(record, "branch", None) or record.classroom.branch
    audit(
        actor,
        branch,
        f"setup.{kind}.updated",
        record,
        {"before": before, "changed_fields": changed_fields},
    )
    return record
