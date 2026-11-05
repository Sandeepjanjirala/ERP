from django.shortcuts import redirect
from django.urls import reverse


class ForcePasswordChangeMiddleware:
    """Until someone replaces their initial password, every page sends them to change it."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        allowed = {reverse("password_change"), reverse("password_change_done"), reverse("logout")}
        if (
            request.user.is_authenticated
            and request.user.must_change_password
            and request.path not in allowed
            and not request.path.startswith("/static/")
        ):
            return redirect("password_change")
        return self.get_response(request)
