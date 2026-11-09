from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.decorators import role_required
from apps.accounts.models import User
from apps.core.pagination import paginate

from .forms import AnnouncementForm
from .selectors import announcements, notifications, unread_count
from .services import mark_read, publish_announcement


@login_required
def announcement_list(request):
    return render(
        request,
        "communication/announcement_list.html",
        {
            "title": "Announcements",
            "page_obj": paginate(request, announcements(request.user), 10),
            "can_post": request.user.role in User.STAFF,
        },
    )


@role_required(*User.STAFF)
def announcement_create(request):
    form = AnnouncementForm(request.POST or None, actor=request.user)
    if request.method == "POST" and form.is_valid():
        publish_announcement(request.user, form.save(commit=False))
        messages.success(request, "Announcement published. Everyone it is for will be notified.")
        return redirect("announcements")
    return render(
        request,
        "form_page.html",
        {
            "title": "New announcement",
            "form": form,
            "description": "Shown on the Announcements page and in each reader's notifications.",
        },
    )


@login_required
def notification_list(request):
    if request.method == "POST":
        mark_read(request.user)
        messages.success(request, "All notifications marked as read.")
        return redirect("notifications")
    return render(
        request,
        "communication/notification_list.html",
        {"title": "Notifications", "page_obj": paginate(request, notifications(request.user))},
    )


@require_GET
@never_cache
def notification_bell(request):
    """The bell with its unread count, for htmx to swap in. Once the session has ended (signed
    out, or the account switched off) it answers 286, which tells htmx to stop polling, rather
    than redirecting and swapping the sign-in page into the top bar."""
    if not request.user.is_authenticated:
        return HttpResponse(status=286)
    return render(
        request, "partials/bell.html", {"unread_notifications": unread_count(request.user)}
    )


@require_POST
@login_required
def notification_open(request, pk):
    """Mark a notification read and go to what it is about."""
    notification = get_object_or_404(notifications(request.user), pk=pk)
    mark_read(request.user, notification)
    safe = url_has_allowed_host_and_scheme(notification.url, allowed_hosts=None)
    return redirect(notification.url if notification.url and safe else "notifications")
