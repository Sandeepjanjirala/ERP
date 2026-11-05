from .models import AuditEvent


def audit(actor, branch, action, target, details=None):
    AuditEvent.objects.create(
        actor=actor, branch=branch, action=action, target=str(target)[:180], details=details or {}
    )
