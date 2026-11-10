from datetime import date

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from apps.academics.models import AcademicYear
from apps.academics.selectors import teacher_lessons
from apps.accounts.decorators import role_required
from apps.accounts.models import User
from apps.accounts.policies import can_manage_account
from apps.audit.selectors import event_areas, events, filter_events
from apps.core.pagination import paginate
from apps.exams.selectors import mark_summary
from apps.fees.selectors import OPEN, fee_summary, invoices, overdue, payments
from apps.organization.selectors import branches, school_name, selected_branch
from apps.students.selectors import guardian_links, students

from .forms import ActivityFilterForm
from .pdf import render_report_card, report_card_filename
from .selectors import (
    SEARCH_LIMIT,
    attendance_trend,
    branch_comparison,
    can_search,
    family_overview,
    low_attendance,
    overview,
    published_marks,
    search_everything,
    subject_performance,
    to_do,
)
from .selectors import student_report as student_report_data
from .services import export_results_csv, records_pack


@login_required
def dashboard(request):
    if request.user.is_family:
        return family_dashboard(request)
    if request.user.is_accountant:
        return accountant_dashboard(request)
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
            "fees": fee_summary(request.user, branch) if request.user.is_finance else None,
            "todays_lessons": todays_lessons(request.user),
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


def todays_lessons(user):
    """A teacher's lessons today, in period order; None for anyone who isn't a teacher."""
    if user.role != User.Role.TEACHER:
        return None
    today = timezone.localdate()
    return teacher_lessons(user).filter(
        weekday=today.isoweekday(),
        classroom__year__starts_on__lte=today,
        classroom__year__ends_on__gte=today,
    )


def accountant_dashboard(request):
    """Today's collections, what is overdue, and what needs a check, for the branch."""
    return render(
        request,
        "reports/accountant_dashboard.html",
        {
            "title": "Overview",
            "fees": fee_summary(request.user),
            "recent_payments": payments(request.user)[:8],
            "overdue_invoices": overdue(invoices(request.user)).order_by("due_on", "pk")[:8],
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
            # Parents only: invoices(user) is empty for students.
            "fees_due": invoices(request.user)
            .filter(student=child, status__in=OPEN)
            .order_by("due_on", "pk"),
        },
    )


@role_required(*User.ACADEMIC)
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


@role_required(*User.ACADEMIC)
def records(request, pk):
    """Every report card, the fee statement and every receipt for a student, in one ZIP: how a
    family keeps their records after leaving (docs/adr/0013-leaving-and-access.md)."""
    student = get_object_or_404(students(request.user), pk=pk)
    response = HttpResponse(records_pack(request.user, student), content_type="application/zip")
    filename = f"records-{student.admission_number}.zip"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@role_required(*User.ACADEMIC)
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


@login_required
def search(request):
    """The global search: students, people and invoices in your scope. htmx swaps in only the
    results as you type; Ctrl+K (or Cmd+K) in the top bar jumps here."""
    if not can_search(request.user):
        raise PermissionDenied
    query = request.GET.get("q", "")
    found = search_everything(request.user, query)
    # People link to their edit page only where the same policy as the service allows it.
    for person in found["people"] or []:
        person.can_edit = can_manage_account(request.user, person)
    return render(
        request,
        "reports/search.html",
        {"title": "Search", "query": query, "found": found, "limit": SEARCH_LIMIT},
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
    """The activity log with its filters; htmx swaps in only the results as filters change."""
    scope = events(request.user)
    form = ActivityFilterForm(request.GET or None, areas=event_areas(scope))
    filtered = scope
    if form.is_valid():
        filtered = filter_events(scope, **form.cleaned_data)
    return render(
        request,
        "reports/activity_log.html",
        {"title": "Activity log", "form": form, "page_obj": paginate(request, filtered)},
    )
