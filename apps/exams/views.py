from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.decorators import role_required
from apps.accounts.models import User
from apps.core.pagination import paginate
from apps.students.selectors import students

from .forms import BandFormSet, ExamForm, MarkSheetForm
from .models import Exam
from .policies import EXAM_AUTHORS, can_manage_grading, can_mark, exam_actions
from .selectors import current_scale, exams, grading_scales, mark_sheet, mark_summary
from .services import (
    DEFAULT_BANDS,
    create_exam,
    save_grading_scale,
    save_marks,
    transition_exam,
)


@role_required(*User.ACADEMIC)
def exam_list(request):
    qs = exams(request.user)
    status = request.GET.get("status", "")
    if status in Exam.Status.values:
        qs = qs.filter(status=status)
    return render(
        request,
        "exams/exam_list.html",
        {
            "title": "Exams & marks",
            "page_obj": paginate(request, qs),
            "status": status,
            # Families only ever see published results, so they get no draft or review tabs.
            "status_tabs": [
                choice
                for choice in Exam.Status.choices
                if not request.user.is_family or choice[0] == Exam.Status.PUBLISHED
            ],
            "can_create": request.user.role in EXAM_AUTHORS,
        },
    )


@role_required(*User.ACADEMIC)
def exam_detail(request, pk):
    exam = get_object_or_404(exams(request.user), pk=pk)
    # The page shows the whole class's marks, so families see their own results instead.
    if request.user.role == User.Role.STUDENT:
        return redirect("student_report", pk=request.user.student_profile.pk)
    if request.user.is_parent:
        child = students(request.user).filter(enrollments__marks__exam=exam).first()
        return redirect("student_report", pk=child.pk)
    sheet = mark_sheet(exam)
    enrolled, marks = sheet["roster"], sheet["marks"]
    writer = can_mark(request.user, exam)
    form = MarkSheetForm(
        request.POST if request.method == "POST" else None, roster=enrolled, marks=marks, exam=exam
    )
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "save":
                if not writer:
                    raise PermissionDenied
                if form.is_valid():
                    entries = {
                        e.pk: (
                            form.cleaned_data[f"score_{e.pk}"],
                            form.cleaned_data[f"absent_{e.pk}"],
                        )
                        for e in enrolled
                    }
                    save_marks(request.user, exam, entries, form.cleaned_data["version"])
                    messages.success(request, "Marks saved as a draft.")
                    return redirect("exam_detail", pk=pk)
            else:
                try:
                    version = int(request.POST.get("version", "0"))
                except ValueError:
                    raise ValidationError("Invalid form version. Reload the page.") from None
                transition_exam(
                    request.user, exam, action, version, request.POST.get("reason", "")[:250]
                )
                messages.success(
                    request,
                    {
                        "submit": "Exam sent to the principal.",
                        "publish": "Results published to students.",
                        "reopen": "Exam reopened. Results are hidden from students until republished.",
                    }[action],
                )
                return redirect("exam_detail", pk=pk)
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
    actions = exam_actions(request.user, exam)
    if not actions["can_edit_marks"]:
        for field in form.fields.values():
            field.disabled = True
    return render(
        request,
        "exams/exam_detail.html",
        {
            "title": exam.title,
            "exam": exam,
            "form": form,
            "can_write": actions["can_edit_marks"],
            "can_submit": actions["can_submit"],
            "can_publish": actions["can_publish"],
            "can_reopen": actions["can_reopen"],
            "summary": mark_summary(marks.values()),
        },
    )


@role_required(*EXAM_AUTHORS)
def exam_create(request):
    form = ExamForm(request.POST or None, actor=request.user)
    if request.method == "POST" and form.is_valid():
        exam = create_exam(request.user, form.save(commit=False))
        messages.success(request, "Exam created. Enter marks, then submit for review.")
        return redirect("exam_detail", pk=exam.pk)
    return render(
        request,
        "form_page.html",
        {
            "title": "Create exam",
            "form": form,
            "description": "Set the maximum and pass mark for this subject assessment.",
        },
    )


@role_required(*User.LEADERS)
def grading_scale(request):
    """The grading scale and its versions. Super admins save a new version; leaders read it."""
    current = current_scale()
    can_edit = can_manage_grading(request.user)
    if current:
        initial = [{"label": b.label, "min_percent": b.min_percent} for b in current.bands.all()]
    else:
        initial = [{"label": label, "min_percent": minimum} for label, minimum in DEFAULT_BANDS]
    formset = None
    if can_edit:
        # Starting values only for showing the form: on a submission, formsets skip extra rows that
        # equal their initial values, and the posted bands would vanish.
        formset = (
            BandFormSet(request.POST) if request.method == "POST" else BandFormSet(initial=initial)
        )
    if request.method == "POST":
        if not can_edit:
            raise PermissionDenied
        if formset.is_valid():
            rows = [form.cleaned_data for form in formset if form.cleaned_data.get("label")]
            try:
                scale = save_grading_scale(request.user, rows)
            except ValidationError as exc:
                formset._non_form_errors = formset.error_class(exc.messages)
            else:
                messages.success(
                    request,
                    f"Version {scale.version} saved. Results already published keep the version "
                    "they were published with.",
                )
                return redirect("grading_scale")
    return render(
        request,
        "exams/grading_scale.html",
        {
            "title": "Grading scale",
            "current": current,
            "versions": grading_scales(),
            "formset": formset,
        },
    )
