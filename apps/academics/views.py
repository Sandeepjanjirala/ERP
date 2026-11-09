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

from .forms import AssignmentForm, ClassroomForm, GradeForm, SubjectForm, TermFormSet, YearForm
from .models import AcademicYear
from .policies import GROUP_LEVEL, can_manage_setup
from .selectors import assignments, classrooms, grades, subjects
from .services import save_setup_record, save_terms, update_setup_record


@role_required(*User.LEADERS)
def setup(request):
    return render(
        request,
        "academics/setup.html",
        {
            "title": "Academic setup",
            "branches": branches(request.user),
            "years": AcademicYear.objects.prefetch_related("terms"),
            "grades": grades(request.user),
            "classrooms": classrooms(request.user).annotate(student_count=Count("enrollments")),
            "subjects": subjects(request.user),
            "assignments": assignments(request.user),
        },
    )


SETUP_FORMS = {
    "organization": OrganizationForm,
    "branch": BranchForm,
    "year": YearForm,
    "grade": GradeForm,
    "classroom": ClassroomForm,
    "subject": SubjectForm,
    "assignment": AssignmentForm,
}


@role_required(*User.MANAGERS)
def setup_create(request, kind):
    # Branch records are checked again in the service, once the form says which branch.
    if kind not in SETUP_FORMS or (
        kind in GROUP_LEVEL and not can_manage_setup(request.user, kind)
    ):
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
        "grade": (grades(request.user), GradeForm, ("branch",)),
        "classroom": (classrooms(request.user), ClassroomForm, ("branch", "year")),
        "subject": (subjects(request.user), SubjectForm, ("branch",)),
        "assignment": (
            assignments(request.user),
            AssignmentForm,
            ("classroom", "subject"),
        ),
    }
    if kind not in editable or (kind in GROUP_LEVEL and not can_manage_setup(request.user, kind)):
        raise PermissionDenied
    queryset, form_class, immutable = editable[kind]
    record = get_object_or_404(queryset, pk=pk)
    before = str(record)
    options = {} if kind in GROUP_LEVEL else {"actor": request.user}
    form = form_class(request.POST or None, instance=record, **options)
    for field in immutable:
        form.fields[field].disabled = True
    if request.method == "POST" and form.is_valid():
        try:
            update_setup_record(
                request.user, kind, form.save(commit=False), before, form.changed_data
            )
        except (ValidationError, IntegrityError) as exc:
            form.add_error(None, error_text(exc, "This record already exists."))
        else:
            messages.success(request, "Changes saved.")
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


@role_required(User.Role.SUPER)
def year_terms(request, pk):
    """All the terms of a year on one form, saved together (see save_terms)."""
    if not can_manage_setup(request.user, "term"):
        raise PermissionDenied
    year = get_object_or_404(AcademicYear, pk=pk)
    initial = [
        {"id": t.pk, "name": t.name, "starts_on": t.starts_on, "ends_on": t.ends_on}
        for t in year.terms.all()
    ]
    formset = TermFormSet(request.POST or None, initial=initial)
    if request.method == "POST" and formset.is_valid():
        rows = [row for form in formset if (row := form.row())]
        try:
            save_terms(request.user, year, rows)
        except ValidationError as exc:
            formset._non_form_errors = formset.error_class(exc.messages)
        else:
            messages.success(request, "Terms saved. Exams are in the term their date falls in.")
            return redirect("setup")
    return render(
        request,
        "academics/year_terms.html",
        {"title": f"Terms of {year.name}", "year": year, "formset": formset},
    )
