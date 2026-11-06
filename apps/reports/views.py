from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.academics.models import AcademicYear
from apps.academics.selectors import classrooms
from apps.accounts.decorators import role_required
from apps.accounts.models import User
from apps.attendance.models import AttendanceSession
from apps.attendance.selectors import attendance_rows, attendance_summary
from apps.audit.selectors import events
from apps.core.pagination import paginate
from apps.exams.models import Exam
from apps.exams.selectors import exams, mark_summary
from apps.organization.selectors import branches, selected_branch
from apps.students.models import Student
from apps.students.selectors import students

from .selectors import published_marks, subject_performance
from .selectors import student_report as student_report_data
from .services import export_results_csv


@login_required
def dashboard(request):
    if request.user.role == User.Role.STUDENT:
        profile = get_object_or_404(Student, user=request.user)
        return redirect("student_report", pk=profile.pk)
    branch = selected_branch(request.user, request.GET.get("branch"))
    classes = classrooms(request.user)
    people = students(request.user)
    exams_qs = exams(request.user)
    attendance = attendance_rows(request.user)
    if branch:
        classes = classes.filter(branch=branch)
        people = people.filter(user__branch=branch)
        exams_qs = exams_qs.filter(classroom__branch=branch)
        attendance = attendance.filter(session__classroom__branch=branch)
    today = timezone.localdate()
    today_attendance = attendance_summary(attendance.filter(session__date=today))
    stats = {
        "students": people.filter(user__is_active=True).count(),
        "classes": classes.count(),
        "pending": exams_qs.filter(status=Exam.Status.SUBMITTED).count(),
        "attendance": today_attendance["rate"],
    }
    class_rows = list(
        classes.annotate(
            student_count=Count(
                "enrollments", filter=Q(enrollments__left_on__isnull=True), distinct=True
            )
        )[:12]
    )
    sessions = {
        s.classroom_id: s
        for s in AttendanceSession.objects.filter(classroom__in=class_rows, date=today)
    }
    for c in class_rows:
        c.register = sessions.get(c.pk)
    return render(
        request,
        "reports/dashboard.html",
        {
            "title": "Overview",
            "stats": stats,
            "class_rows": class_rows,
            "recent_exams": exams_qs[:5],
            "branches": branches(request.user),
            "selected_branch": branch,
            "today": today,
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
