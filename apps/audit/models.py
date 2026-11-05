from django.conf import settings
from django.db import models

from apps.organization.models import Branch


class AuditEvent(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.PROTECT)
    action = models.CharField(max_length=80)
    target = models.CharField(max_length=180)
    details = models.JSONField(default=dict, blank=True)  # many events have nothing extra
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # pk breaks ties so paginated pages never repeat or skip an event.
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.action} · {self.target}"
