from .selectors import unread_count


def notifications(request):
    """The unread count on the notification bell, for signed-in pages."""
    if not request.user.is_authenticated:
        return {}
    return {"unread_notifications": unread_count(request.user)}
