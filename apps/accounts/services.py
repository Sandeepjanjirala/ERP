from datetime import timedelta

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from apps.audit.services import audit

from .models import User
from .policies import can_change_access, can_manage_account

CONTACT_FIELDS = ("first_name", "last_name", "email", "phone")


@transaction.atomic
def create_account(actor, user, password):
    """Save a new account with a hashed password; the person must change it at first sign-in."""
    if not can_manage_account(actor, user):
        raise PermissionDenied
    validate_password(password, user=user)
    user.set_password(password)
    user.must_change_password = True
    user.save()
    audit(actor, user.branch, "account.created", user.username, {"role": user.role})
    return user


@transaction.atomic
def change_password(user, current_password, new_password):
    """The owner replaces their password, which also completes a forced first-login change."""
    if not user.check_password(current_password):
        raise ValidationError(
            {"current_password": "Your current password was entered incorrectly."}
        )
    try:
        validate_password(new_password, user=user)
    except ValidationError as exc:
        raise ValidationError({"new_password": exc.messages}) from None
    user.set_password(new_password)
    user.must_change_password = False
    user.save(update_fields=["password", "must_change_password"])
    audit(user, user.branch, "account.password_changed", user.username)
    return user


@transaction.atomic
def toggle_access(actor, person):
    """Deactivate an active account, or reactivate an inactive one."""
    person = User.objects.select_for_update().get(pk=person.pk)
    if not can_change_access(actor, person):
        raise PermissionDenied
    person.is_active = not person.is_active
    if person.is_active and person.deactivated_reason:
        # Switching back on an account the access review switched off (a leaver): it gets a
        # fresh grace period, after which the review switches it off again.
        person.access_ends_on = timezone.localdate() + timedelta(days=settings.LEAVER_GRACE_DAYS)
    person.deactivated_reason = ""
    person.save(update_fields=["is_active", "deactivated_reason", "access_ends_on"])
    if not person.is_active:
        revoke_access(person)
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


def revoke_access(person):
    """End every way in for a switched-off account: its web sessions are deleted and its API
    refresh tokens blacklisted, so reactivating it later doesn't revive them. (While switched off,
    Django and the API already refuse it, because both check is_active.)"""
    live = Session.objects.filter(expire_date__gt=timezone.now())
    stale = [s.session_key for s in live if s.get_decoded().get("_auth_user_id") == str(person.pk)]
    Session.objects.filter(session_key__in=stale).delete()
    outstanding = OutstandingToken.objects.filter(user=person, blacklistedtoken__isnull=True)
    BlacklistedToken.objects.bulk_create(BlacklistedToken(token=token) for token in outstanding)


@transaction.atomic
def set_access(person, active, reason="", actor=None):
    """Switch an account on or off for an automatic rule (the daily access review). Audited with
    the reason; switching off revokes sessions and tokens. Returns True if anything changed."""
    person = User.objects.select_for_update().get(pk=person.pk)
    if person.is_active == active:
        return False
    person.is_active = active
    person.deactivated_reason = "" if active else reason
    if active:
        person.access_ends_on = None
    person.save(update_fields=["is_active", "deactivated_reason", "access_ends_on"])
    if not active:
        revoke_access(person)
    action = "account.reactivated_automatically" if active else "account.deactivated_automatically"
    details = {"reason": reason, "by": actor.username if actor else "the daily access review"}
    audit(actor or person, person.branch, action, person.username, details)
    return True
