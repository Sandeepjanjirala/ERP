from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.decorators import role_required
from apps.accounts.models import User
from apps.core.exceptions import error_text
from apps.core.pagination import paginate
from apps.organization.selectors import branches, selected_branch

from .forms import EnrollmentForm, GuardianAccountForm, LinkGuardianForm, StudentAccountForm
from .selectors import guardian_links, students
from .services import (
    add_guardian_account,
    admit_student,
    enroll,
    link_guardian,
    make_primary_guardian,
)


@role_required(*User.STAFF)
def student_list(request):
    qs = students(request.user).order_by("user__first_name", "admission_number")
    query = request.GET.get("q", "").strip()
    if query:
        qs = qs.filter(
            Q(user__first_name__icontains=query)
            | Q(user__last_name__icontains=query)
            | Q(admission_number__icontains=query)
        )
    branch = selected_branch(request.user, request.GET.get("branch"))
    if branch:
        qs = qs.filter(user__branch=branch)
    return render(
        request,
        "students/student_list.html",
        {
            "title": "Students",
            "page_obj": paginate(request, qs),
            "query": query,
            "branches": branches(request.user),
            "selected_branch": branch,
        },
    )


@role_required(*User.MANAGERS)
def student_create(request):
    form = StudentAccountForm(request.POST or None, actor=request.user)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            student = admit_student(
                request.user,
                form.save(commit=False),
                data["password"],
                data["admission_number"],
                data["classroom"],
                data["joined_on"],
            )
        except (ValidationError, IntegrityError) as exc:
            form.add_error(
                None,
                error_text(
                    exc,
                    "A matching account or enrollment already exists. Please review the details.",
                ),
            )
        else:
            messages.success(
                request,
                f"{student.user.display_name} can now sign in. Their first login requires a password change.",
            )
            return redirect("students")
    return render(
        request,
        "form_page.html",
        {
            "title": "Add student",
            "form": form,
            "description": "Accounts belong to one branch. Initial passwords must be shared privately.",
        },
    )


@role_required(*User.MANAGERS)
def enrollment_create(request):
    form = EnrollmentForm(request.POST or None, actor=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            enroll(request.user, form.save(commit=False))
        except (ValidationError, IntegrityError) as exc:
            form.add_error(None, error_text(exc, "This record already exists."))
        else:
            messages.success(request, "Saved successfully.")
            return redirect("setup")
    return render(
        request,
        "form_page.html",
        {
            "title": "Set up enrollment",
            "form": form,
            "description": "Choose matching branch, classroom, and academic-year details.",
        },
    )


@role_required(*User.MANAGERS)
def guardian_create(request, pk):
    student = get_object_or_404(students(request.user), pk=pk)
    # The form validates the new account as a whole, so it must already be a parent in the
    # student's branch (the service sets the same values).
    form = GuardianAccountForm(
        request.POST or None, instance=User(role=User.Role.PARENT, branch=student.user.branch)
    )
    if request.method == "POST" and form.is_valid():
        try:
            link = add_guardian_account(
                request.user,
                form.save(commit=False),
                form.cleaned_data["password"],
                student,
                form.cleaned_data["relationship"],
                form.cleaned_data["make_primary"],
            )
        except (ValidationError, IntegrityError) as exc:
            form.add_error(None, error_text(exc, "A matching account already exists."))
        else:
            messages.success(
                request,
                f"{link.guardian} can now sign in. Their first login requires a password change.",
            )
            return redirect("student_report", pk=student.pk)
    return render(
        request,
        "form_page.html",
        {
            "title": f"Add a parent for {student.user.display_name}",
            "form": form,
            "description": "Creates the parent's own login. Initial passwords must be shared privately.",
        },
    )


@role_required(*User.MANAGERS)
def guardian_link(request, pk):
    student = get_object_or_404(students(request.user), pk=pk)
    form = LinkGuardianForm(request.POST or None, student=student)
    if request.method == "POST" and form.is_valid():
        try:
            link_guardian(
                request.user,
                student,
                form.cleaned_data["parent"],
                form.cleaned_data["relationship"],
                form.cleaned_data["make_primary"],
            )
        except (ValidationError, IntegrityError) as exc:
            form.add_error(None, error_text(exc, "This parent is already linked."))
        else:
            messages.success(request, "Parent linked.")
            return redirect("student_report", pk=student.pk)
    return render(
        request,
        "form_page.html",
        {
            "title": f"Link a parent to {student.user.display_name}",
            "form": form,
            "description": "For a brother or sister of a student already at the school.",
        },
    )


@require_POST
@role_required(*User.MANAGERS)
def guardian_make_primary(request, pk, link_pk):
    link = get_object_or_404(guardian_links(request.user), pk=link_pk, student_id=pk)
    make_primary_guardian(request.user, link)
    messages.success(request, f"{link.guardian} is now the primary contact.")
    return redirect("student_report", pk=pk)
