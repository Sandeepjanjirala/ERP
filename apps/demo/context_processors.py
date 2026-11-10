from django.conf import settings

from .services import DEMO_LOGINS


def demo(request):
    """The one-click logins on the demo's sign-in page."""
    if not settings.DEMO_MODE:
        return {}
    return {"demo_logins": [(role, label) for role, (label, _) in DEMO_LOGINS.items()]}
