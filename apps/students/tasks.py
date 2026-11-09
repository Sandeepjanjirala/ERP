from celery import shared_task
from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMessage, get_connection
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from apps.accounts.models import User
from apps.organization.selectors import school_name

from .models import ImportBatch


@shared_task
def send_import_invites(batch_id):
    """Email each account an import created a link to set their own password.

    The batch is locked and stamped when the emails go, so a retried job sends nothing twice.
    """
    with transaction.atomic():
        batch = ImportBatch.objects.select_for_update().get(pk=batch_id)
        if batch.invites_sent_at:
            return 0
        people = User.objects.filter(username__in=batch.accounts, is_active=True).select_related(
            "branch"
        )
        messages = []
        for person in people:
            link = reverse(
                "password_reset_confirm",
                kwargs={
                    "uidb64": urlsafe_base64_encode(force_bytes(person.pk)),
                    "token": default_token_generator.make_token(person),
                },
            )
            body = render_to_string(
                "students/import_invite.txt",
                {
                    "person": person,
                    "school": school_name(),
                    "link": f"{settings.SITE_URL}{link}",
                    "days": settings.PASSWORD_RESET_TIMEOUT // 86400,
                },
            )
            messages.append(
                EmailMessage(f"Your account at {school_name()}", body, to=[person.email])
            )
        get_connection().send_messages(messages)
        batch.invites_sent_at = timezone.now()
        batch.save(update_fields=["invites_sent_at"])
    return len(messages)


@shared_task
def review_account_access():
    """The nightly access review (students.services.review_access)."""
    from .services import review_access  # here, not at the top: services imports this module

    return review_access()


@shared_task
def send_access_ending_notice(parent_id, fees_owed=False):
    """Tell a parent whose children have all left when their sign-in ends, and how to download
    their children's records (and pay what is owed) before then."""
    parent = User.objects.filter(pk=parent_id, is_active=True).exclude(email="").first()
    if parent is None or parent.access_ends_on is None:
        return 0
    body = render_to_string(
        "students/access_ending.txt",
        {
            "person": parent,
            "school": school_name(),
            "ends_on": parent.access_ends_on,
            "fees_owed": fees_owed,
            "fees_link": f"{settings.SITE_URL}{reverse('fees')}",
            "link": f"{settings.SITE_URL}{reverse('dashboard')}",
        },
    )
    EmailMessage(f"Your access to {school_name()} is ending", body, to=[parent.email]).send()
    return 1
