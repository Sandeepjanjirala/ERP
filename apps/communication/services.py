from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mass_mail
from django.db import transaction
from django.utils import timezone

from apps.audit.services import audit
from apps.core.jobs import run_after_commit

from .models import Notification
from .policies import can_announce


@transaction.atomic
def publish_announcement(actor, announcement):
    """Save an announcement and deliver it to its audience in the background."""
    announcement.author = actor
    if not can_announce(actor, announcement):
        raise PermissionDenied
    announcement.save()
    audit(
        actor,
        announcement.branch,
        "announcement.published",
        announcement,
        {"audience": announcement.audience},
    )
    from .tasks import deliver_announcement  # tasks import this module

    run_after_commit(deliver_announcement, announcement.pk)
    return announcement


def notify(recipients, kind, key, title, body="", url="", email=False):
    """Put a message in each recipient's notification bell, and optionally email it.

    `key` names the event (e.g. "absence:41:2026-11-06"). Anyone who already has a notification
    with that key is skipped, so a job that runs twice notifies and emails nobody twice; the
    database's unique (recipient, key) constraint backs this up. Returns the number notified.
    """
    recipients = {person.pk: person for person in recipients if person.is_active}
    already = set(
        Notification.objects.filter(key=key, recipient__in=recipients).values_list(
            "recipient_id", flat=True
        )
    )
    new = [person for pk, person in recipients.items() if pk not in already]
    Notification.objects.bulk_create(
        [
            Notification(
                recipient=person, kind=kind, key=key, title=title[:160], body=body[:500], url=url
            )
            for person in new
        ],
        ignore_conflicts=True,
    )
    if email:
        link = f"\n\n{settings.SITE_URL}{url}" if url else ""
        footer = f"\n\n— {settings.BRAND['name']}"
        # One message per person: recipients never see each other's addresses.
        send_mass_mail(
            [
                (title, f"{body}{link}{footer}", None, [person.email])
                for person in new
                if person.email
            ]
        )
    return len(new)


def mark_read(user, notification=None):
    """Mark one of the user's notifications read, or all of them. Returns how many changed."""
    unread = user.notifications.filter(read_at__isnull=True)
    if notification is not None:
        unread = unread.filter(pk=notification.pk)
    return unread.update(read_at=timezone.now())
