from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.decorators import role_required
from apps.accounts.models import User
from apps.core.exceptions import error_text
from apps.organization.forms import BranchForm, OrganizationForm
from apps.organization.models import Organization
from apps.organization.selectors import branches

from .forms import AssignmentForm, ClassroomForm, SubjectForm, YearForm
from .models import AcademicYear, Subject, TeachingAssignment
from .selectors import classrooms
from .services import save_setup_record, update_setup_record


@role_required(*User.LEADERS)
def setup(request):
    return render(
        request,
        "academics/setup.html",
        {
            "title": "Academic setup",
            "branches": branches(request.user),
            "years": AcademicYear.objects.all(),
            "classrooms": classrooms(request.user).annotate(student_count=Count("enrollments")),
            "subjects": Subject.objects.filter(branch__in=branches(request.user)),
            "assignments": TeachingAssignment.objects.filter(
                classroom__in=classrooms(request.user)
            ).select_related("teacher", "classroom__branch", "classroom__year", "subject"),
        },
    )


SETUP_FORMS = {
    "organization": OrganizationForm,
    "branch": BranchForm,
    "year": YearForm,
    "classroom": ClassroomForm,
    "subject": SubjectForm,
    "assignment": AssignmentForm,
}
# Records that belong to the whole school group, not one branch: super admins only.
GROUP_LEVEL = ("organization", "branch", "year")


@role_required(*User.MANAGERS)
def setup_create(request, kind):
    if kind not in SETUP_FORMS or (kind in GROUP_LEVEL and not request.user.system_admin):
        raise PermissionDenied
    options = {} if kind in GROUP_LEVEL else {"actor": request.user}
    if kind == "organization":
        options["instance"] = Organization.objects.first()
    form = SETUP_FORMS[kind](request.POST or None, **options)
    if request.method == "POST" and form.is_valid():
        try:
            save_setup_record(request.user, kind, form.save(commit=False))
        except (ValidationError, IntegrityError) as exc:
            form.add_error(None, error_text(exc, "This record already exists."))
        else:
            messages.success(request, "Saved successfully.")
            return redirect("setup")
    return render(
        request,
        "form_page.html",
        {
            "title": f"Set up {kind}",
            "form": form,
            "description": "Choose matching branch, classroom, and academic-year details.",
        },
    )


@role_required(*User.MANAGERS)
def setup_edit(request, kind, pk):
    editable = {
        "classroom": (classrooms(request.user), ClassroomForm, ("branch", "year")),
        "subject": (
            Subject.objects.filter(branch__in=branches(request.user)),
            SubjectForm,
            ("branch",),
        ),
        "assignment": (
            TeachingAssignment.objects.filter(classroom__in=classrooms(request.user)),
            AssignmentForm,
            ("classroom", "subject"),
        ),
    }
    if kind not in editable:
        raise PermissionDenied
    queryset, form_class, immutable = editable[kind]
    record = get_object_or_404(queryset, pk=pk)
    before = str(record)
    form = form_class(request.POST or None, instance=record, actor=request.user)
    for field in immutable:
        form.fields[field].disabled = True
    if request.method == "POST" and form.is_valid():
        update_setup_record(request.user, kind, form.save(commit=False), before, form.changed_data)
        messages.success(request, "Assignment details updated.")
        return redirect("setup")
    return render(
        request,
        "form_page.html",
        {
            "title": f"Edit {kind}",
            "form": form,
            "description": "Branch and academic-year boundaries are preserved. Changes are recorded in the activity log.",
        },
    )
