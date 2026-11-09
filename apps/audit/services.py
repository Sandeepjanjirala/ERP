from apps.core.request_id import current_request_id

from .models import AuditEvent


def audit(actor, branch, action, target, details=None):
    AuditEvent.objects.create(
        actor=actor,
        branch=branch,
        action=action,
        target=str(target)[:180],
        details=details or {},
        request_id=current_request_id(),
    )
