from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.decorators import role_required
from apps.accounts.models import User
from apps.core.exceptions import error_text
from apps.core.pagination import paginate
from apps.organization.selectors import branches, selected_branch

from .forms import (
    EnrollmentForm,
    GuardianAccountForm,
    ImportForm,
    LeavingForm,
    LinkGuardianForm,
    PromotionForm,
    StudentAccountForm,
)
from .imports import COLUMNS, read_csv, template_csv
from .selectors import enrollments, guardian_links, import_batches, students
from .services import (
    DECISIONS,
    add_guardian_account,
    admit_student,
    check_import,
    confirm_import,
    enroll,
    link_guardian,
    make_primary_guardian,
    promote_class,
    promotion_preview,
    record_leaving,
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
def enrollment_leave(request, pk):
    """Record that a student has left. Their records stay; their sign-in stops the next day and
    their parents' after the grace period (docs/adr/0013-leaving-and-access.md)."""
    enrollment = get_object_or_404(enrollments(request.user), pk=pk)
    form = LeavingForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            record_leaving(request.user, enrollment, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, error_text(exc))
        else:
            messages.success(
                request, f"{enrollment.student.user.display_name}'s leaving is recorded."
            )
            return redirect("student_report", pk=enrollment.student_id)
    student = enrollment.student.user.display_name
    return render(
        request,
        "form_page.html",
        {
            "title": f"Record that {student} has left",
            "form": form,
            "description": (
                f"{enrollment.classroom}, {enrollment.classroom.year}. Nothing is deleted: "
                f"{student}'s sign-in stops the day after, and their parents can still sign in "
                f"for {settings.LEAVER_GRACE_DAYS} days (longer while fees are owed) to download "
                "records."
            ),
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


# CSV import --------------------------------------------------------------------------------


@role_required(*User.MANAGERS)
def student_import(request):
    """Upload a CSV. Every row is checked as a real import would, then nothing is kept but the
    check: the preview comes next."""
    form = ImportForm(request.POST or None, request.FILES or None, actor=request.user)
    if request.method == "POST" and form.is_valid():
        upload = form.cleaned_data["file"]
        try:
            rows = read_csv(upload)
        except ValidationError as exc:
            form.add_error("file", exc.messages)
        else:
            batch = check_import(
                request.user,
                form.cleaned_data["branch"],
                form.cleaned_data["year"],
                upload.name,
                rows,
            )
            return redirect("student_import_preview", batch.pk)
    return render(
        request,
        "students/import.html",
        {
            "title": "Import students",
            "form": form,
            "columns": COLUMNS,
            "recent": import_batches(request.user)[:10],
        },
    )


@role_required(*User.MANAGERS)
def student_import_template(request):
    response = HttpResponse(template_csv(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="students-import-template.csv"'
    return response


@role_required(*User.MANAGERS)
def student_import_preview(request, pk):
    batch = get_object_or_404(import_batches(request.user), pk=pk)
    rows = [
        {"number": number, "row": row, "problems": batch.errors.get(str(number), [])}
        for number, row in enumerate(batch.rows, start=2)
    ]
    return render(
        request,
        "students/import_preview.html",
        {"title": f"Import: {batch.filename}", "batch": batch, "rows": rows},
    )


@require_POST
@role_required(*User.MANAGERS)
def student_import_confirm(request, pk):
    batch = get_object_or_404(import_batches(request.user), pk=pk)
    already = batch.status == batch.Status.IMPORTED
    try:
        batch = confirm_import(request.user, batch)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        return redirect("student_import_preview", batch.pk)
    if batch.errors:
        messages.error(
            request,
            "Something changed since the check, so nothing was imported. See the problems below.",
        )
        return redirect("student_import_preview", batch.pk)
    if already:
        messages.info(request, "This file was already imported.")
    else:
        messages.success(
            request,
            f"{len(batch.rows)} students imported. New accounts are being sent a link to set "
            "their password.",
        )
    return redirect("student_import_preview", batch.pk)


# Year-end promotion ----------------------------------------------------------------------------


@role_required(*User.LEADERS)
def promotion(request):
    """Choose the classes, check each student's decision, then move the class on in one go."""
    form = PromotionForm(request.GET or None, actor=request.user)
    context = {"title": "Year-end promotion", "form": form, "decisions": DECISIONS, "rows": None}
    if not form.is_valid():
        return render(request, "students/promotion.html", context)
    source, target = form.cleaned_data["source"], form.cleaned_data["target"]
    repeat = form.cleaned_data["repeat"]
    if request.method == "POST":
        decisions = {
            int(key.removeprefix("decision_")): value
            for key, value in request.POST.items()
            if key.startswith("decision_") and key.removeprefix("decision_").isdigit()
        }
        try:
            counts = promote_class(request.user, source, decisions, target, repeat)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(
                request,
                f"{counts['promote']} moved up, {counts['repeat']} repeat, {counts['leave']} left"
                + (
                    f", {counts['already_moved']} were already moved"
                    if counts["already_moved"]
                    else ""
                )
                + ".",
            )
            return redirect(request.get_full_path())
    context["rows"] = promotion_preview(source)
    context.update(source=source, target=target, repeat=repeat)
    return render(request, "students/promotion.html", context)
