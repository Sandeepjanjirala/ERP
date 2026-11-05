from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect, render

from apps.accounts.decorators import role_required
from apps.accounts.models import User
from apps.students.selectors import roster

from .forms import RegisterForm, RegisterSelection
from .models import AttendanceSession
from .policies import can_attend
from .services import save_register


@role_required(*User.STAFF)
def attendance(request):
    selection = RegisterSelection(request.GET or None, actor=request.user)
    context = {"title": "Daily attendance", "selection": selection}
    if not selection.is_valid():
        return render(request, "attendance/register.html", context)
    classroom, day = selection.cleaned_data["classroom"], selection.cleaned_data["date"]
    enrolled = list(roster(classroom, day))
    session = AttendanceSession.objects.filter(classroom=classroom, date=day).first()
    statuses = dict(session.records.values_list("enrollment_id", "status")) if session else {}
    writable = can_attend(request.user, classroom)
    form = RegisterForm(
        request.POST if request.method == "POST" else None,
        roster=enrolled,
        initial_statuses=statuses,
        version=session.version if session else 0,
    )
    if request.method == "POST":
        if not writable:
            raise PermissionDenied
        if form.is_valid():
            try:
                save_register(
                    request.user,
                    classroom,
                    day,
                    {e.pk: form.cleaned_data[f"status_{e.pk}"] for e in enrolled},
                    form.cleaned_data["version"],
                    form.cleaned_data["reason"],
                )
                messages.success(request, "Daily attendance saved.")
                return redirect(request.get_full_path())
            except ValidationError as exc:
                form.add_error(None, "; ".join(exc.messages))
    if not writable:
        for field in form.fields.values():
            field.disabled = True
    context.update(
        {
            "classroom": classroom,
            "day": day,
            "form": form,
            "can_write": writable,
            "session": session,
            "roster_count": len(enrolled),
        }
    )
    return render(request, "attendance/register.html", context)
