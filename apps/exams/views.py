from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.decorators import role_required
from apps.accounts.models import User
from apps.core.pagination import paginate
from apps.students.selectors import roster

from .forms import ExamForm, MarkSheetForm
from .models import Exam
from .policies import can_mark, can_publish
from .selectors import exams, mark_summary
from .services import create_exam, save_marks, transition_exam

# Roles that may create exams (teachers only for their own class and subject).
EXAM_AUTHORS = (User.Role.SUPER, User.Role.ADMIN, User.Role.TEACHER)


@login_required
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
            "can_create": request.user.role in EXAM_AUTHORS,
        },
    )


@login_required
def exam_detail(request, pk):
    exam = get_object_or_404(exams(request.user), pk=pk)
    if request.user.role == User.Role.STUDENT:
        return redirect("student_report", pk=request.user.student_profile.pk)
    enrolled = list(roster(exam.classroom, exam.date))
    marks = {
        m.enrollment_id: m for m in exam.marks.select_related("enrollment__student__user", "exam")
    }
    writer, publisher = can_mark(request.user, exam), can_publish(request.user, exam)
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
    writable = writer and exam.status == Exam.Status.DRAFT
    if not writable:
        for field in form.fields.values():
            field.disabled = True
    return render(
        request,
        "exams/exam_detail.html",
        {
            "title": exam.title,
            "exam": exam,
            "form": form,
            "can_write": writable,
            "can_submit": writer and exam.status == Exam.Status.DRAFT,
            "can_publish": publisher,
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
