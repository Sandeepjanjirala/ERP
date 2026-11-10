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
    # The web request that wrote it (see apps/core/request_id.py); empty for background jobs.
    request_id = models.CharField(max_length=32, blank=True, editable=False)

    class Meta:
        # pk breaks ties so paginated pages never repeat or skip an event.
        ordering = ["-created_at", "-pk"]
        # The activity log's filters: a branch's newest events, one action, one person.
        indexes = [
            models.Index(fields=["branch", "-created_at"], name="audit_branch_recent"),
            models.Index(fields=["action", "-created_at"], name="audit_action_recent"),
            models.Index(fields=["actor", "-created_at"], name="audit_actor_recent"),
            models.Index(fields=["request_id"], name="audit_request"),
        ]

    def __str__(self):
        return f"{self.action} · {self.target}"
