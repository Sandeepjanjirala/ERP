from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.accounts.decorators import role_required
from apps.accounts.models import User
from apps.core.pagination import paginate

from .forms import AnnouncementForm
from .selectors import announcements, notifications
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


@require_POST
@login_required
def notification_open(request, pk):
    """Mark a notification read and go to what it is about."""
    notification = get_object_or_404(notifications(request.user), pk=pk)
    mark_read(request.user, notification)
    safe = url_has_allowed_host_and_scheme(notification.url, allowed_hosts=None)
    return redirect(notification.url if notification.url and safe else "notifications")
