from django.contrib import messages
from django.contrib.auth import login
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from .services import demo_account


@require_POST
def demo_login(request, role):
    """One-click sign-in as a seeded demo account. A 404 anywhere but the demo."""
    account = demo_account(role)
    if account is None:
        raise Http404
    if not account.is_active:
        messages.error(
            request,
            "Another visitor switched this demo account off. It comes back at the nightly reset.",
        )
        return redirect("login")
    login(request, account, backend="django.contrib.auth.backends.ModelBackend")
    return redirect("dashboard")
