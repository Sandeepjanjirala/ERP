from .decorators import LEADERS, MANAGERS


def role_flags(request):
    """Shortcuts for templates that show or hide management links."""
    user = request.user
    return {
        "is_manager": user.is_authenticated and user.role in MANAGERS,
        "is_leader": user.is_authenticated and user.role in LEADERS,
    }
