import csv
from collections import defaultdict

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.academics.models import AcademicYear
from apps.academics.selectors import classrooms
from apps.accounts.decorators import LEADERS, role_required
from apps.attendance.models import AttendanceSession
from apps.attendance.selectors import attendance_rows, attendance_summary
from apps.audit.selectors import events
from apps.audit.services import audit
from apps.core.pagination import paginate
from apps.exams.models import Mark
from apps.exams.selectors import exams, mark_summary
from apps.organization.selectors import branches, selected_branch
from apps.students.models import Student
from apps.students.selectors import enrollments, students


@login_required
def dashboard(request):
    if request.user.role == "student":
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
        "pending": exams_qs.filter(status="submitted").count(),
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
    student_enrollments = enrollments(request.user).filter(student=student)
    year_id = request.GET.get("year")
    year = (
        get_object_or_404(AcademicYear, pk=year_id)
        if year_id and year_id.isdigit()
        else AcademicYear.objects.filter(enrollment__in=student_enrollments).distinct().first()
    )
    if year:
        student_enrollments = student_enrollments.filter(year=year)
    marks = list(
        Mark.objects.filter(
            enrollment__in=student_enrollments,
            exam__in=exams(request.user).filter(status="published"),
        ).select_related("exam__subject", "exam__classroom")
    )
    rows = (
        attendance_rows(request.user)
        .filter(enrollment__in=student_enrollments)
        .order_by("-session__date")
    )
    return render(
        request,
        "reports/student_report.html",
        {
            "title": "Student report",
            "student": student,
            "enrollments": student_enrollments,
            "marks": marks,
            "summary": mark_summary(marks),
            "attendance_summary": attendance_summary(rows),
            "attendance_page": paginate(request, rows, 15),
            "years": AcademicYear.objects.filter(enrollment__student=student).distinct(),
            "selected_year": year,
        },
    )


def safe_csv(value):
    text = str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else text


@role_required("superadmin", "admin", "principal", "teacher")
def reports(request):
    permitted = exams(request.user).filter(status="published")
    year_id = request.GET.get("year")
    if year_id and year_id.isdigit():
        permitted = permitted.filter(classroom__year_id=year_id)
    branch = selected_branch(request.user, request.GET.get("branch"))
    if branch:
        permitted = permitted.filter(classroom__branch=branch)
    marks = list(
        Mark.objects.filter(exam__in=permitted).select_related(
            "exam__subject", "exam__classroom__branch", "enrollment__student__user"
        )
    )
    if request.GET.get("format") == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="published-results.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "Branch",
                "Class",
                "Student",
                "Admission number",
                "Subject",
                "Exam",
                "Score",
                "Maximum",
                "Result",
            ]
        )
        for m in marks:
            writer.writerow(
                [
                    safe_csv(x)
                    for x in [
                        m.exam.classroom.branch.name,
                        f"{m.exam.classroom.grade}-{m.exam.classroom.section}",
                        m.enrollment.student.user.display_name,
                        m.enrollment.student.admission_number,
                        m.exam.subject.name,
                        m.exam.title,
                        "Absent" if m.absent else m.score,
                        m.exam.max_marks,
                        "Pass" if m.passed else "Below pass mark",
                    ]
                ]
            )
        audit(
            request.user,
            branch or request.user.branch,
            "report.exported",
            "Published results CSV",
            {"rows": len(marks)},
        )
        return response
    groups = defaultdict(list)
    for m in marks:
        groups[(m.exam.classroom.branch.name, m.exam.subject.name)].append(m)
    subjects = [
        {"branch": k[0], "name": k[1], **mark_summary(v)} for k, v in sorted(groups.items())
    ]
    return render(
        request,
        "reports/performance.html",
        {
            "title": "Performance analysis",
            "summary": mark_summary(marks),
            "subjects": subjects,
            "years": AcademicYear.objects.all(),
            "year_id": year_id or "",
            "branches": branches(request.user),
            "selected_branch": branch,
        },
    )


@role_required(*LEADERS)
def audit_log(request):
    return render(
        request,
        "reports/activity_log.html",
        {"title": "Activity log", "page_obj": paginate(request, events(request.user))},
    )
