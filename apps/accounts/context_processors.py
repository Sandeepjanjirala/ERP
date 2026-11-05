def role_flags(request):
    """Shortcuts for templates that show or hide management links."""
    user = request.user
    return {
        "is_manager": user.is_authenticated and user.is_manager,
        "is_leader": user.is_authenticated and user.is_leader,
    }
