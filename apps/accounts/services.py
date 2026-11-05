from django.core.exceptions import PermissionDenied
from django.db import transaction

from apps.audit.services import audit

from .models import User
from .policies import can_change_access, can_manage_account

CONTACT_FIELDS = ("first_name", "last_name", "email")


@transaction.atomic
def create_account(actor, user, password):
    """Save a new account with a hashed password; the person must change it at first sign-in."""
    user.set_password(password)
    user.must_change_password = True
    user.save()
    audit(actor, user.branch, "account.created", user.username, {"role": user.role})
    return user


@transaction.atomic
def toggle_access(actor, person):
    """Deactivate an active account, or reactivate an inactive one."""
    person = User.objects.select_for_update().get(pk=person.pk)
    if not can_change_access(actor, person):
        raise PermissionDenied
    person.is_active = not person.is_active
    person.save(update_fields=["is_active"])
    action = "account.activated" if person.is_active else "account.deactivated"
    audit(actor, person.branch, action, person.username)
    return person


@transaction.atomic
def update_contact_details(actor, person):
    """Save a person's name and email. Role, branch and system permissions cannot change here."""
    stored = User.objects.select_for_update().get(pk=person.pk)
    if not can_manage_account(actor, stored):
        raise PermissionDenied
    before = {field: getattr(stored, field) for field in CONTACT_FIELDS}
    person.save(update_fields=CONTACT_FIELDS)
    after = {field: getattr(person, field) for field in CONTACT_FIELDS}
    audit(
        actor,
        person.branch,
        "account.profile_updated",
        person.username,
        {"before": before, "after": after},
    )
    return person
