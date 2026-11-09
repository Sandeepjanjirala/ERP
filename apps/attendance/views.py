from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.decorators import role_required
from apps.accounts.models import User
from apps.core.pagination import paginate

from .forms import LeaveDecisionForm, LeaveRequestForm, RegisterForm, RegisterSelection
from .models import Attendance, LeaveRequest
from .policies import can_attend
from .selectors import daily_register, leave_enrollments, leave_requests
from .services import decide_leave, request_leave, save_register


def _register_context(request, classroom, day, data=None):
    """The register for one class and day, with a form bound to `data` when given."""
    register = daily_register(classroom, day)
    enrolled, session = register["roster"], register["session"]
    writable = can_attend(request.user, classroom)
    form = RegisterForm(
        data,
        roster=enrolled,
        # Approved leave suggests "Excused" until the register is saved; saved statuses win.
        initial_statuses={
            **dict.fromkeys(register["on_leave"], Attendance.Status.EXCUSED),
            **register["statuses"],
        },
        version=session.version if session else 0,
    )
    if not writable:
        for field in form.fields.values():
            field.disabled = True
    return {
        "classroom": classroom,
        "day": day,
        "form": form,
        "enrolled": enrolled,
        "can_write": writable,
        "session": session,
        "roster_count": len(enrolled),
        "on_leave": register["on_leave"],
    }


@role_required(*User.STAFF)
def attendance(request):
    """The daily register. One tap per student; "Mark all present" fills the form without
    saving. With htmx, filling and saving replace only the register card."""
    selection = RegisterSelection(request.GET or None, actor=request.user)
    context = {"title": "Daily attendance", "selection": selection}
    if not selection.is_valid():
        return render(request, "attendance/register.html", context)
    classroom, day = selection.cleaned_data["classroom"], selection.cleaned_data["date"]
    htmx = bool(request.headers.get("HX-Request"))
    template = "attendance/_register.html" if htmx else "attendance/register.html"
    if request.method != "POST":
        return render(request, template, {**context, **_register_context(request, classroom, day)})
    if not can_attend(request.user, classroom):
        raise PermissionDenied
    fill = request.POST.get("fill")
    data = request.POST.copy()
    register = _register_context(request, classroom, day, data)
    if fill in Attendance.Status.values:
        for enrollment in register["enrolled"]:
            data[f"status_{enrollment.pk}"] = fill
        register = _register_context(request, classroom, day, data)
        register["notice"] = "Everyone is marked present. Change anyone who isn't, then save."
        return render(request, template, {**context, **register})
    form = register["form"]
    if form.is_valid():
        try:
            save_register(
                request.user,
                classroom,
                day,
                {e.pk: form.cleaned_data[f"status_{e.pk}"] for e in register["enrolled"]},
                form.cleaned_data["version"],
                form.cleaned_data["reason"],
            )
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
        else:
            if not htmx:
                messages.success(request, "Daily attendance saved.")
                return redirect(request.get_full_path())
            # A fresh, unbound register (with the new version number) and a confirmation.
            register = _register_context(request, classroom, day)
            register["notice"] = "Daily attendance saved."
    return render(request, template, {**context, **register})


@role_required(*User.ACADEMIC)
def leave_list(request):
    requests = leave_requests(request.user)
    status = request.GET.get("status", "")
    if status in LeaveRequest.Status.values:
        requests = requests.filter(status=status)
    page_obj = paginate(request, requests)
    # Each row offers approve/reject only to people who may decide it (the register's keepers).
    enrollments = leave_enrollments(page_obj)
    for leave in page_obj:
        enrollment = enrollments[leave.pk]
        leave.can_decide = (
            leave.status == LeaveRequest.Status.PENDING
            and enrollment is not None
            and can_attend(request.user, enrollment.classroom)
        )
    return render(
        request,
        "attendance/leave_list.html",
        {
            "title": "Leave requests",
            "page_obj": page_obj,
            "status": status,
            "status_tabs": LeaveRequest.Status.choices,
            "can_request": request.user.is_parent,
        },
    )


@role_required(User.Role.PARENT)
def leave_create(request):
    form = LeaveRequestForm(request.POST or None, actor=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            request_leave(request.user, form.save(commit=False))
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
        else:
            messages.success(request, "Request sent to the class teacher.")
            return redirect("leave_requests")
    return render(
        request,
        "form_page.html",
        {
            "title": "Apply for leave",
            "form": form,
            "description": "The class teacher decides. Approved days show as Excused on the register.",
        },
    )


@require_POST
@role_required(*User.ACADEMIC)
def leave_decide(request, pk):
    leave = get_object_or_404(leave_requests(request.user), pk=pk)
    form = LeaveDecisionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Choose approve or not approve.")
        return redirect("leave_requests")
    try:
        decide_leave(
            request.user,
            leave,
            form.cleaned_data["decision"] == "approve",
            form.cleaned_data["note"],
        )
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    else:
        messages.success(request, "Decision saved. The family will be notified.")
    return redirect("leave_requests")
