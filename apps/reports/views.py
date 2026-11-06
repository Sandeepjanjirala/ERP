from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.academics.models import AcademicYear
from apps.accounts.decorators import role_required
from apps.accounts.models import User
from apps.audit.selectors import events
from apps.core.pagination import paginate
from apps.exams.selectors import mark_summary
from apps.organization.selectors import branches, selected_branch
from apps.students.selectors import guardian_links, students

from .pdf import render_report_card, report_card_filename, school_name
from .selectors import (
    attendance_trend,
    branch_comparison,
    family_overview,
    low_attendance,
    overview,
    published_marks,
    subject_performance,
    to_do,
)
from .selectors import student_report as student_report_data
from .services import export_results_csv


@login_required
def dashboard(request):
    if request.user.is_family:
        return family_dashboard(request)
    branch = selected_branch(request.user, request.GET.get("branch"))
    trend = attendance_trend(request.user, branch)
    return render(
        request,
        "reports/dashboard.html",
        {
            "title": "Overview",
            **overview(request.user, branch),
            "to_do": to_do(request.user),
            "low_attendance": low_attendance(request.user, branch),
            "branches": branches(request.user),
            "selected_branch": branch,
            "has_trend": bool(trend),
            "charts": {
                "trend": [
                    {"label": date.fromisoformat(p["date"]).strftime("%d %b"), "rate": p["rate"]}
                    for p in trend
                ],
                "branches": branch_comparison(request.user),
            },
        },
    )


def family_dashboard(request):
    """Students see themselves; parents pick one of their children with ?child=."""
    children = list(students(request.user).order_by("user__first_name", "pk"))
    if not children:
        return render(request, "reports/no_children.html", {"title": "Overview"})
    chosen = request.GET.get("child")
    child = get_object_or_404(students(request.user), pk=chosen) if chosen else children[0]
    return render(
        request,
        "reports/family_dashboard.html",
        {
            "title": "Overview",
            "children": children,
            "student": child,
            **family_overview(request.user, child),
        },
    )


@login_required
def report_card(request, pk):
    """The student report as a printable PDF report card."""
    student = get_object_or_404(students(request.user), pk=pk)
    report = student_report_data(request.user, student, request.GET.get("year"))
    response = HttpResponse(
        render_report_card(student, report, school_name()), content_type="application/pdf"
    )
    filename = report_card_filename(student, report)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


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
            "guardians": guardian_links(request.user).filter(student=student),
            "can_manage_guardians": request.user.is_manager,
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
