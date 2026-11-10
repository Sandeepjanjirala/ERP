from .selectors import can_search


def search(request):
    """Whether the top bar shows the global search box."""
    return {"can_search": request.user.is_authenticated and can_search(request.user)}
