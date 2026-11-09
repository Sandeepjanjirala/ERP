"""End-to-end walkthrough of every EduNexa feature (Phases 1 to 5), as each role, through the full
Django request stack: views, middleware, templates, services and the database.

It runs on upgraded legacy data: the single-app version's demo data, exported, converted and loaded
(e2e/rehearse_upgrade.py does all of it). It changes that data, so use a throwaway database.

    DATABASE_URL=postgresql://.../upgraded python e2e/walkthrough.py OLD_PASSWORD
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
import django  # noqa: E402

django.setup()
from django.test.utils import setup_test_environment  # noqa: E402

setup_test_environment()  # lets test clients see template context, as in tests
from datetime import time, timedelta  # noqa: E402

from django.contrib.auth import authenticate  # noqa: E402
from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402
from django.test import Client  # noqa: E402
from django.urls import reverse  # noqa: E402
from django.utils import timezone  # noqa: E402

from apps.academics.models import AcademicYear, Classroom, Grade, Period, Subject, TimetableSlot  # noqa: E402
from apps.accounts.models import User  # noqa: E402
from apps.attendance.models import AttendanceSession  # noqa: E402
from apps.audit.models import AuditEvent  # noqa: E402
from apps.exams.models import Exam, GradingScale, Mark  # noqa: E402
from apps.students.models import Enrollment, ImportBatch, Student  # noqa: E402

OLD_PASSWORD = sys.argv[1]
NEW_PASSWORD = "Smoke-test-strong-password-7734!"
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not condition:
        failures.append(name)


def as_user(username):
    client = Client(HTTP_HOST="127.0.0.1")
    client.force_login(User.objects.get(username=username))
    return client


today = timezone.localdate()
audit_before = AuditEvent.objects.count()

# 1. Upgraded accounts still sign in with their old passwords, through the real login view.
check("old password still valid", authenticate(username="superadmin", password=OLD_PASSWORD))
visitor = Client(HTTP_HOST="127.0.0.1")
response = visitor.post(
    reverse("login"), {"username": "principal.madhapur", "password": OLD_PASSWORD}
)
check(
    "login page signs in", response.status_code == 302 and response.url == "/", response.status_code
)
check("health endpoint", visitor.get("/health/").status_code == 200)

# 2. Every page renders for every role, with no server errors.
pages = ["/", "/students/", "/attendance/", "/exams/", "/reports/", "/setup/", "/users/", "/activity/",
         "/users/new/", "/students/new/", "/exams/new/", "/setup/subject/new/", "/setup/enrollment/new/",
         "/accounts/password/change/", "/timetable/", "/exams/grading/", "/students/import/",
         "/students/promotion/"]  # fmt: skip
leaders_only = {"/students/promotion/", "/exams/grading/"}
managers_only = {
    "/users/new/",
    "/students/new/",
    "/setup/subject/new/",
    "/setup/enrollment/new/",
    "/students/import/",
}
expected_ok = {
    "superadmin": set(pages),
    "admin.madhapur": set(pages),
    "principal.madhapur": set(pages) - managers_only - {"/exams/new/"},
    "teacher.madhapur": {"/", "/students/", "/attendance/", "/exams/", "/reports/", "/exams/new/", "/accounts/password/change/", "/timetable/"},
    "student1.madhapur": {"/", "/exams/", "/accounts/password/change/", "/timetable/"},
}  # fmt: skip
for username, allowed in expected_ok.items():
    client = as_user(username)
    for path in pages:
        status = client.get(path, follow=True).status_code
        want = 200 if path in allowed else 403
        check(f"{username} GET {path}", status == want, f"got {status}, want {want}")

# 3. Daily attendance: correcting a register needs a reason, then saves and bumps the version.
classroom = Classroom.objects.get(branch__code="madhapur")
session = AttendanceSession.objects.filter(classroom=classroom).latest("date")
register_url = reverse("attendance") + f"?classroom={classroom.pk}&date={session.date.isoformat()}"
statuses = {f"status_{record.enrollment_id}": "P" for record in session.records.all()}
teacher = as_user("teacher.madhapur")
response = teacher.post(register_url, {"version": session.version, "reason": "", **statuses})
check(
    "register correction without reason is refused", "Enter a reason" in response.content.decode()
)
response = teacher.post(
    register_url, {"version": session.version, "reason": "Smoke test correction", **statuses}
)
check("register correction saved", response.status_code == 302, response.status_code)
session_after = AttendanceSession.objects.get(pk=session.pk)
check("register version bumped", session_after.version == session.version + 1)
response = teacher.post(
    register_url, {"version": session.version, "reason": "stale tab", **statuses}
)
check(
    "stale register tab is rejected",
    "Another user changed this register" in response.content.decode(),
)
response = teacher.post(
    register_url,
    {"version": session_after.version, "reason": "htmx", **statuses},
    HTTP_HX_REQUEST="true",
)
check(
    "htmx register save returns only the register",
    response.status_code == 200
    and b"<html" not in response.content
    and b"Daily attendance saved." in response.content,
)
session_after.refresh_from_db()
mentor_register = as_user("mentor.madhapur").post(
    register_url, {"version": session_after.version, "reason": "x", **statuses}
)
check(
    "non-class-teacher cannot record register",
    mentor_register.status_code == 403,
    mentor_register.status_code,
)

# 4. Result workflow: publish (with the grading scale), reopen, re-enter marks, resubmit.
superadmin = as_user("superadmin")
bands = {"form-TOTAL_FORMS": "8", "form-INITIAL_FORMS": "0"}
for n, (label, minimum) in enumerate(
    [("A1", 91), ("A2", 81), ("B1", 71), ("B2", 61), ("C1", 51), ("C2", 41), ("D", 33), ("E", 0)]
):
    bands |= {f"form-{n}-label": label, f"form-{n}-min_percent": minimum}
response = superadmin.post(reverse("grading_scale"), bands)
check(
    "super admin saves grading scale v1",
    response.status_code == 302 and GradingScale.objects.filter(version=1).exists(),
)
science = Exam.objects.get(classroom=classroom, subject__name="Science")
check(
    "upgraded exam sits in a term",
    science.term_id is not None and science.term.starts_on <= science.date <= science.term.ends_on,
)
principal = as_user("principal.madhapur")
url = reverse("exam_detail", args=[science.pk])
response = principal.post(url, {"action": "publish", "version": science.version})
science.refresh_from_db()
check("principal publishes submitted exam", science.status == "published", science.status)
check("publishing freezes scale v1", science.grading_scale and science.grading_scale.version == 1)
student = as_user("student1.madhapur")
own = Student.objects.get(user__username="student1.madhapur")
report = student.get(reverse("student_report", args=[own.pk]))
check(
    "student sees newly published result",
    report.context["summary"]["count"] == 2,
    report.context["summary"]["count"],
)
graded = [m for m in report.context["marks"] if m.exam_id == science.pk]
check(
    "the new result has a grade; older ones have none",
    graded
    and graded[0].grade_label
    and all(m.grade_label is None for m in report.context["marks"] if m.exam_id != science.pk),
)
response = principal.post(
    url, {"action": "reopen", "version": science.version, "reason": "Smoke test reopen"}
)
science.refresh_from_db()
check(
    "principal reopens with reason",
    science.status == "draft" and science.grading_scale is None,
    science.status,
)
report = student.get(reverse("student_report", args=[own.pk]))
check("reopened result hidden from student", report.context["summary"]["count"] == 1)
enrolled = Enrollment.objects.filter(classroom=classroom)
marks = {f"score_{e.pk}": "41" for e in enrolled}
math_teacher_save = as_user("teacher.madhapur").post(
    url, {"action": "save", "version": science.version, **marks}
)
check(
    "other subject's teacher cannot enter marks",
    math_teacher_save.status_code == 403,
    math_teacher_save.status_code,
)
mentor = as_user("mentor.madhapur")
response = mentor.post(url, {"action": "save", "version": science.version, **marks})
check("subject teacher saves marks", response.status_code == 302, response.status_code)
check(
    "marks stored", set(Mark.objects.filter(exam=science).values_list("score", flat=True)) == {41}
)
science.refresh_from_db()
response = mentor.post(url, {"action": "submit", "version": science.version})
science.refresh_from_db()
check("teacher resubmits for review", science.status == "submitted", science.status)

# 5. People & access: create staff, forced password change, edit, deactivate, reactivate.
admin = as_user("admin.madhapur")
branch_id = classroom.branch_id
response = admin.post(reverse("user_create"), {"username": "smoke.teacher", "first_name": "Smoke", "last_name": "Teacher", "email": "smoke.teacher@example.invalid", "password": NEW_PASSWORD, "role": "teacher", "branch": branch_id})  # fmt: skip
check("admin creates teacher", response.status_code == 302, response.status_code)
newcomer = Client(HTTP_HOST="127.0.0.1")
newcomer.post(reverse("login"), {"username": "smoke.teacher", "password": NEW_PASSWORD})
check("new account forced to change password", newcomer.get("/").url == reverse("password_change"))
response = newcomer.post(reverse("password_change"), {"old_password": NEW_PASSWORD, "new_password1": NEW_PASSWORD + "x", "new_password2": NEW_PASSWORD + "x"})  # fmt: skip
check(
    "password changed, dashboard opens",
    response.status_code == 302 and newcomer.get("/").status_code == 200,
)
mentor_user = User.objects.get(username="mentor.madhapur")
response = admin.post(reverse("user_edit", args=[mentor_user.pk]), {"first_name": "Ravi", "last_name": "Kumar", "email": "ravi.updated@example.invalid"})  # fmt: skip
mentor_user.refresh_from_db()
check("admin edits contact details", mentor_user.email == "ravi.updated@example.invalid")
admin.post(reverse("toggle_user", args=[mentor_user.pk]))
mentor_user.refresh_from_db()
check("admin deactivates teacher", not mentor_user.is_active)
admin.post(reverse("toggle_user", args=[mentor_user.pk]))
mentor_user.refresh_from_db()
check("admin reactivates teacher", mentor_user.is_active)
principal_user = User.objects.get(username="principal.madhapur")
check(
    "admin cannot deactivate principal",
    admin.post(reverse("toggle_user", args=[principal_user.pk])).status_code == 403,
)

# 6. Admission and setup.
admission = {"username": "smoke.student", "first_name": "Smoke", "last_name": "Student", "email": "smoke.student@example.invalid", "password": NEW_PASSWORD, "role": "student", "branch": branch_id, "admission_number": "SMOKE-1", "classroom": classroom.pk}  # fmt: skip
last_register = session.date
response = admin.post(
    reverse("student_create"), {**admission, "joined_on": last_register.isoformat()}
)
check(
    "joining on a day with a completed register is refused",
    "would change a completed register" in response.content.decode(),
)
check(
    "refused admission created nothing", not User.objects.filter(username="smoke.student").exists()
)
response = admin.post(
    reverse("student_create"),
    {**admission, "joined_on": (last_register + timedelta(days=1)).isoformat()},
)
check(
    "admin admits student from the day after the last register",
    response.status_code == 302
    and Enrollment.objects.filter(student__admission_number="SMOKE-1").exists(),
)
response = admin.post(
    reverse("setup_create", args=["subject"]),
    {"branch": branch_id, "name": "History", "code": "history"},
)
check(
    "admin creates subject",
    response.status_code == 302 and Subject.objects.filter(code="history").exists(),
)

# 7. Reports, export and isolation.
csv = principal.get(reverse("reports") + "?format=csv")
check(
    "CSV export",
    csv.status_code == 200
    and csv["Content-Type"].startswith("text/csv")
    and b"Mathematics" in csv.content,
)
foreign = Student.objects.filter(user__branch__code="benz-circle").first()
check(
    "other branch's student is hidden (404)",
    admin.get(reverse("student_report", args=[foreign.pk])).status_code == 404,
)
other = Student.objects.filter(user__branch__code="madhapur").exclude(pk=own.pk).first()
check(
    "student cannot open a classmate's report (404)",
    student.get(reverse("student_report", args=[other.pk])).status_code == 404,
)
log = principal.get(reverse("audit")).content.decode()
check(
    "activity log records the changes",
    "attendance.saved" in log and AuditEvent.objects.count() > audit_before,
)

# 8. Fees on the upgraded data: an accountant, a fee plan, invoices, a payment and its receipt.
from apps.fees.models import FeeHead, FeePlan, Invoice, Payment  # noqa: E402

response = admin.post(reverse("user_create"), {"username": "smoke.accountant", "first_name": "Smoke", "last_name": "Accounts", "email": "smoke.accountant@example.invalid", "password": NEW_PASSWORD, "role": "accountant", "branch": branch_id})  # fmt: skip
check("admin creates accountant", response.status_code == 302, response.status_code)
response = admin.post(
    reverse("fee_head_create", args=[branch_id]), {"name": "Tuition", "code": "tuition"}
)
check(
    "admin adds fee head",
    response.status_code == 302 and FeeHead.objects.filter(code="tuition").exists(),
)
tuition = FeeHead.objects.get(code="tuition", branch_id=branch_id)
response = admin.post(reverse("fee_plan_create", args=[branch_id]), {"year": classroom.year_id, "grade": classroom.grade_id, f"head_{tuition.pk}": "12,500"})  # fmt: skip
plan = FeePlan.objects.filter(branch_id=branch_id, grade=classroom.grade).first()
check(
    "admin adds fee plan for the upgraded grade",
    response.status_code == 302 and plan is not None,
    response.status_code,
)
User.objects.filter(username="smoke.accountant").update(must_change_password=False)
accountant = as_user("smoke.accountant")
response = accountant.post(reverse("invoices_issue", args=[plan.pk]), {"title": "Smoke term", "due_on": (today + timedelta(days=7)).isoformat()}, follow=True)  # fmt: skip
issued = Invoice.objects.filter(plan=plan, title="Smoke term")
check(
    "accountant issues invoices to the class",
    issued.count() == Enrollment.objects.filter(classroom=classroom).count() > 0,
    issued.count(),
)
invoice = issued.order_by("pk").first()
response = accountant.post(
    reverse("payment_record", args=[invoice.pk]), {"amount": "5,000", "method": "cash"}
)
payment = Payment.objects.filter(invoice=invoice).first()
check(
    "accountant records a cash payment",
    response.status_code == 302 and payment is not None,
    response.status_code,
)
check(
    "receipt numbered from the branch code",
    payment.receipt.number.endswith("/00001"),
    payment.receipt.number,
)
pdf = accountant.get(reverse("receipt_pdf", args=[payment.receipt.pk]))
check("receipt PDF downloads", pdf["Content-Type"] == "application/pdf")
invoice.refresh_from_db()
check(
    "invoice partly paid",
    (invoice.status, invoice.balance_paise) == ("partly_paid", 750000),
    invoice.status,
)
check("accountant sees no exams (403)", accountant.get("/exams/").status_code == 403)
check("teacher sees no fees (403)", as_user("teacher.madhapur").get("/fees/").status_code == 403)
check("student sees no fees (403)", student.get("/fees/").status_code == 403)
for path in (
    "/fees/",
    "/fees/setup/",
    "/fees/review/",
    "/fees/collections/",
    f"/fees/invoices/{invoice.pk}/",
):
    check(f"accountant GET {path}", accountant.get(path).status_code == 200)

# 9. Phase 5: terms, periods and timetable, CSV import, promotion, the activity log's filters.
year = classroom.year
first, second = year.terms.order_by("starts_on")
terms_url = reverse("year_terms", args=[year.pk])
boundary = first.ends_on + timedelta(days=1)
form = {"form-TOTAL_FORMS": "2", "form-INITIAL_FORMS": "2",
        "form-0-id": first.pk, "form-0-name": "Term 1", "form-0-starts_on": first.starts_on, "form-0-ends_on": boundary,
        "form-1-id": second.pk, "form-1-name": "Term 2", "form-1-starts_on": boundary + timedelta(days=1), "form-1-ends_on": second.ends_on}  # fmt: skip
response = superadmin.post(terms_url, form)
check(
    "super admin moves the term boundary (both terms together)",
    response.status_code == 302,
    response.status_code,
)
check("branch admin may not change terms (403)", admin.get(terms_url).status_code == 403)
for n, (starts, ends) in enumerate(
    [(time(8, 30), time(9, 15)), (time(9, 20), time(10, 5))], start=1
):
    admin.post(
        reverse("setup_create", args=["period"]),
        {
            "branch": branch_id,
            "number": n,
            "starts_at": starts.strftime("%H:%M"),
            "ends_at": ends.strftime("%H:%M"),
        },
    )
p1 = Period.objects.get(branch_id=branch_id, number=1)
math = classroom.teaching.get(subject__name="Mathematics")
cell = reverse("timetable_cell", args=[classroom.pk])
response = admin.post(
    cell, {"weekday": 1, "period": p1.pk, "assignment": math.pk}, HTTP_HX_REQUEST="true"
)
check(
    "admin plans a lesson with htmx",
    b"Saved" in response.content and TimetableSlot.objects.filter(classroom=classroom).count() == 1,
)
grade10 = Grade.objects.create(branch_id=branch_id, name="Class 10", order=10)
other_class = Classroom.objects.create(branch_id=branch_id, year=year, grade=grade10, section="A")
other_class.teaching.create(teacher=math.teacher, subject=math.subject)
clash = admin.post(
    reverse("timetable_cell", args=[other_class.pk]),
    {"weekday": 1, "period": p1.pk, "assignment": other_class.teaching.get().pk},
    HTTP_HX_REQUEST="true",
)
check(
    "the same teacher in another class at that time is refused",
    b"already teaches" in clash.content and TimetableSlot.objects.count() == 1,
)
check(
    "teacher sees the lesson in their week", teacher.get(reverse("my_timetable")).status_code == 200
)
check(
    "student sees the class timetable",
    student.get(reverse("classroom_timetable", args=[classroom.pk])).status_code == 200,
)

csv_text = f"admission_number,first_name,last_name,email,classroom,joined_on\nIMP-1,Imported,One,imported.one@example.invalid,{classroom.grade.name}-{classroom.section},{(last_register + timedelta(days=1)).isoformat()}\n"
upload = SimpleUploadedFile("students.csv", csv_text.encode(), content_type="text/csv")
response = admin.post(
    reverse("student_import"), {"branch": branch_id, "year": year.pk, "file": upload}
)
batch = ImportBatch.objects.order_by("-pk").first()
check(
    "CSV import checks every row first",
    response.status_code == 302
    and batch
    and batch.ready
    and not Student.objects.filter(admission_number="IMP-1").exists(),
)
response = admin.post(reverse("student_import_confirm", args=[batch.pk]), follow=True)
check(
    "confirming imports the row",
    Student.objects.filter(admission_number="IMP-1").exists()
    and b"students imported" in response.content,
)

next_year = AcademicYear.objects.create(
    name="Next year",
    starts_on=year.ends_on + timedelta(days=1),
    ends_on=year.ends_on + timedelta(days=365),
)
from apps.academics.services import default_terms  # noqa: E402

default_terms(next_year)
target = Classroom.objects.create(branch_id=branch_id, year=next_year, grade=grade10, section="A")
promotion_url = reverse("promotion") + f"?source={classroom.pk}&target={target.pk}"
rows = principal.get(promotion_url).context["rows"]
decisions = {f"decision_{row['enrollment'].pk}": "promote" for row in rows}
response = principal.post(promotion_url, decisions, follow=True)
moved = Enrollment.objects.filter(year=next_year).count()
check("principal moves the class up", moved == len(rows) and b"moved up" in response.content, moved)
principal.post(promotion_url, decisions)
check(
    "running the promotion again changes nothing",
    Enrollment.objects.filter(year=next_year).count() == moved,
)

response = admin.post(
    reverse("setup_create", args=["subject"]),
    {"branch": branch_id, "name": "Music", "code": "music"},
)
request_id = response["X-Request-ID"]
found = admin.get(reverse("audit"), {"request": request_id}).context["page_obj"]
check(
    "the activity log finds a request's entries by its id",
    [e.action for e in found] == ["setup.subject.saved"],
)
check(
    "the activity log filters by area",
    all(
        e.action.startswith("timetable")
        for e in admin.get(reverse("audit"), {"area": "timetable"}).context["page_obj"]
    ),
)

print(f"\n{len(failures)} failures" if failures else "\nALL CHECKS PASSED")
sys.exit(1 if failures else 0)
