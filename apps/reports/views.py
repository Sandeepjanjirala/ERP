from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.academics.models import AcademicYear
from apps.accounts.decorators import role_required
from apps.accounts.models import User
from apps.audit.selectors import events
from apps.core.pagination import paginate
from apps.exams.selectors import mark_summary
from apps.organization.selectors import branches, selected_branch
from apps.students.models import Student
from apps.students.selectors import students

from .selectors import overview, published_marks, subject_performance
from .selectors import student_report as student_report_data
from .services import export_results_csv


@login_required
def dashboard(request):
    if request.user.role == User.Role.STUDENT:
        profile = get_object_or_404(Student, user=request.user)
        return redirect("student_report", pk=profile.pk)
    if request.user.is_parent:
        child = students(request.user).order_by("user__first_name", "pk").first()
        if child:
            return redirect("student_report", pk=child.pk)
        return render(request, "reports/no_children.html", {"title": "Overview"})
    branch = selected_branch(request.user, request.GET.get("branch"))
    return render(
        request,
        "reports/dashboard.html",
        {
            "title": "Overview",
            **overview(request.user, branch),
            "branches": branches(request.user),
            "selected_branch": branch,
        },
    )


@login_required
def student_report(request, pk):
    student = get_object_or_404(students(request.user), pk=pk)
    report = student_report_data(request.user, student, request.GET.get("year"))
    return render(
        request,
        "reports/student_report.html",
        {
            "title": "Student report",
            "student": student,
            **report,
            "attendance_page": paginate(request, report["attendance_rows"], 15),
        },
    )


@role_required(*User.STAFF)
def reports(request):
    branch = selected_branch(request.user, request.GET.get("branch"))
    year_id = request.GET.get("year")
    marks = published_marks(request.user, year_id, branch)
    if request.GET.get("format") == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="published-results.csv"'
        export_results_csv(request.user, branch, marks, response)
        return response
    return render(
        request,
        "reports/performance.html",
        {
            "title": "Performance analysis",
            "summary": mark_summary(marks),
            "subjects": subject_performance(marks),
            "years": AcademicYear.objects.all(),
            "year_id": year_id or "",
            "branches": branches(request.user),
            "selected_branch": branch,
        },
    )


@role_required(*User.LEADERS)
def audit_log(request):
    return render(
        request,
        "reports/activity_log.html",
        {"title": "Activity log", "page_obj": paginate(request, events(request.user))},
    )
