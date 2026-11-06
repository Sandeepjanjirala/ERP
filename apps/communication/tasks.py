from celery import shared_task
from django.urls import reverse

from .models import Announcement, Notification
from .selectors import announcement_audience
from .services import notify


@shared_task
def deliver_announcement(announcement_id):
    """Notify everyone in an announcement's audience. Safe to run twice."""
    announcement = Announcement.objects.select_related("branch", "classroom").get(
        pk=announcement_id
    )
    return notify(
        announcement_audience(announcement),
        Notification.Kind.ANNOUNCEMENT,
        f"announcement:{announcement.pk}",
        announcement.title,
        announcement.body,
        url=f"{reverse('announcements')}#announcement-{announcement.pk}",
    )
