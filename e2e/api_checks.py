"""Drive the EduNexa API over real HTTP with real JWTs, like a mobile app would.

    python e2e/api_checks.py BASE_URL DEMO_PASSWORD [MAILPIT_URL]

Needs a freshly seeded throwaway server (`manage.py seed_demo --size small`) with a Celery worker,
and Mailpit (default http://127.0.0.1:8025) to read the emails background jobs send, as the
Docker Compose stack provides. It changes the data, so never point it at a real school.
"""

import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import date, timedelta

BASE, PASSWORD = sys.argv[1].rstrip("/"), sys.argv[2]
MAILPIT = (sys.argv[3] if len(sys.argv) > 3 else "http://127.0.0.1:8025").rstrip("/")
NEW_PASSWORD = "Api-e2e-strong-password-5521!"
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not condition:
        failures.append(name)


def call(
    method, path, body=None, token=None, accept="application/json", raw=None, content_type=None
):
    headers = {"Accept": accept}
    data = None
    if raw is not None:
        data, headers["Content-Type"] = raw, content_type
    elif body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            status, payload, head = response.status, response.read(), response.headers
    except urllib.error.HTTPError as error:
        status, payload, head = error.code, error.read(), error.headers
    try:
        payload = (
            json.loads(payload) if payload and "json" in head.get("Content-Type", "") else payload
        )
    except ValueError:
        pass
    return status, payload, head


def sign_in(username, password=PASSWORD):
    status, body, _ = call(
        "POST", "/api/v1/auth/token/", {"username": username, "password": password}
    )
    return status, body


def eventually(condition, seconds=15):
    """With a real Celery worker, notifications arrive a moment after the request."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.25)
    return condition()


def multipart(fields, files):
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    for name, (filename, content) in files.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            "Content-Type: text/csv\r\n\r\n".encode()
            + content
            + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


# 1. Anonymous callers and the docs.
status, body, head = call("GET", "/api/v1/students/")
check(
    "anonymous request is 401 with the common error shape",
    status == 401 and body["code"] == "not_authenticated",
)
check("API responses are never cached", head.get("Cache-Control") == "no-store, private")
check("every response carries a request id", len(head.get("X-Request-ID", "")) == 32)
for path in ("/api/schema/", "/api/docs/", "/api/redoc/"):
    status, _, head = call("GET", path, accept="*/*")
    check(
        f"public {path}",
        status == 200 and "script-src 'self'" in head.get("Content-Security-Policy", ""),
    )

# 2. Teacher: sign in, find their class, take today's register.
status, tokens = sign_in("teacher.madhapur")
check("teacher signs in with JWT", status == 200 and {"access", "refresh"} <= set(tokens), status)
teacher = tokens["access"]
_, me, _ = call("GET", "/api/v1/me/", token=teacher)
check("/me/ says teacher", me["role"] == "teacher", me.get("role"))
_, classes, _ = call("GET", "/api/v1/classrooms/?page_size=100", token=teacher)
homeroom = next(
    c for c in classes["results"] if (c["homeroom_teacher"] or {}).get("id") == me["id"]
)
check(
    "classrooms keep the grade name and add grade_id",
    isinstance(homeroom["grade"], str) and isinstance(homeroom["grade_id"], int),
)
url = f"/api/v1/classrooms/{homeroom['id']}/register/"
_, register, _ = call("GET", url, token=teacher)
check(
    "register loads with a version and the class list",
    register["students"] and "version" in register,
)
records = [{"enrollment": s["enrollment"], "status": "P"} for s in register["students"]]
body = {"version": register["version"], "records": records, "reason": "API end-to-end check"}
status, saved, _ = call("PUT", url, body, token=teacher)
check("register saved", status == 200 and saved["version"] == register["version"] + 1, status)
status, stale, _ = call("PUT", url, body, token=teacher)
check(
    "stale register version is 409 Conflict", status == 409 and stale["code"] == "conflict", status
)

# 3. Marks and the result workflow.
_, visible, _ = call("GET", "/api/v1/exams/?page_size=100", token=teacher)
pairs = {(e["classroom"]["id"], e["subject"]["id"]) for e in visible["results"]}
check(
    "exams show their term", all(e["term"]["name"].startswith("Term ") for e in visible["results"])
)
exam, refused = None, 0
for classroom_id, subject_id in sorted(pairs):
    new_exam = {"classroom": classroom_id, "subject": subject_id, "title": "API end-to-end quiz",
                "date": date.today().isoformat(), "max_marks": "50", "pass_marks": "20"}  # fmt: skip
    status, created, _ = call("POST", "/api/v1/exams/", new_exam, token=teacher)
    if status == 201:
        exam = exam or created
    elif status == 403:
        refused += 1
check(
    "teacher creates an exam for their own class and subject",
    exam is not None and exam["status"] == "draft",
)
check("other subjects in the class are refused (403)", refused >= 1, f"{refused} refused")
outside = {
    **new_exam,
    "classroom": exam["classroom"]["id"],
    "subject": exam["subject"]["id"],
    "title": "Way off",
    "date": "1999-01-01",
}
status, body, _ = call("POST", "/api/v1/exams/", outside, token=teacher)
check("an exam date outside the year is refused (400)", status == 400, status)
_, sheet, _ = call("GET", f"/api/v1/exams/{exam['id']}/marks/", token=teacher)
marks = [
    {"enrollment": row["enrollment"], "score": "40", "absent": False} for row in sheet["students"]
]
status, saved, _ = call(
    "PUT",
    f"/api/v1/exams/{exam['id']}/marks/",
    {"version": exam["version"], "marks": marks},
    token=teacher,
)
check("marks saved", status == 200, saved if status != 200 else "")
version = saved["exam"]["version"]
status, submitted, _ = call(
    "POST", f"/api/v1/exams/{exam['id']}/submit/", {"version": version}, token=teacher
)
check("teacher submits", status == 200 and submitted["status"] == "submitted", status)
status, _, _ = call(
    "POST", f"/api/v1/exams/{exam['id']}/publish/", {"version": submitted["version"]}, token=teacher
)
check("teacher cannot publish (403)", status == 403, status)
_, principal_tokens = sign_in("principal.madhapur")
status, published, _ = call(
    "POST",
    f"/api/v1/exams/{exam['id']}/publish/",
    {"version": submitted["version"]},
    token=principal_tokens["access"],
)
check("principal publishes", status == 200 and published["status"] == "published", status)

# 4. Token rotation and sign-out.
status, rotated, _ = call("POST", "/api/v1/auth/token/refresh/", {"refresh": tokens["refresh"]})
check(
    "refresh returns a new pair", status == 200 and rotated["refresh"] != tokens["refresh"], status
)
status, _, _ = call("POST", "/api/v1/auth/token/refresh/", {"refresh": tokens["refresh"]})
check("an already-used refresh token is refused", status == 401, status)
status, _, _ = call("POST", "/api/v1/auth/logout/", {"refresh": rotated["refresh"]})
check("logout", status == 200, status)
status, _, _ = call("POST", "/api/v1/auth/token/refresh/", {"refresh": rotated["refresh"]})
check("refresh after logout is refused", status == 401, status)

# 5. Admin creates a teacher, who must change the password before anything else.
_, admin_tokens = sign_in("admin.madhapur")
admin = admin_tokens["access"]
_, me_admin, _ = call("GET", "/api/v1/me/", token=admin)
status, person, _ = call(
    "POST",
    "/api/v1/people/",
    {
        "username": "api.e2e",
        "first_name": "Api",
        "last_name": "Check",
        "email": "api.e2e@example.invalid",
        "role": "teacher",
        "password": NEW_PASSWORD,
    },
    token=admin,
)
check(
    "admin creates a teacher in their own branch",
    status == 201 and person["branch"]["id"] == me_admin["branch"]["id"],
    status,
)
status, newcomer = sign_in("api.e2e", NEW_PASSWORD)
check(
    "new account must change password", status == 200 and newcomer["must_change_password"] is True
)
status, blocked, _ = call("GET", "/api/v1/classrooms/", token=newcomer["access"])
check(
    "other endpoints wait for the change (403)",
    status == 403 and blocked["code"] == "password_change_required",
    status,
)
status, fresh, _ = call(
    "POST",
    "/api/v1/me/password/",
    {"current_password": NEW_PASSWORD, "new_password": NEW_PASSWORD + "x"},
    token=newcomer["access"],
)
check("password changed, new tokens issued", status == 200 and "access" in fresh, status)
status, _, _ = call("GET", "/api/v1/classrooms/", token=newcomer["access"])
check("the old token was revoked by the change (401)", status == 401, status)
status, _, _ = call("GET", "/api/v1/classrooms/", token=fresh["access"])
check("the new token works", status == 200, status)

# 6. Shared sign-in limit: 8 wrong passwords, then even the right one waits.
for _ in range(8):
    sign_in("api.e2e", "wrong-password")
status, _ = sign_in("api.e2e", NEW_PASSWORD + "x")
check("sign-in is throttled after 8 failures (429)", status == 429, status)

# 7. Reports and scope.
status, csv, head = call(
    "GET",
    "/api/v1/reports/performance/export/",
    token=principal_tokens["access"],
    accept="text/csv",
)
check(
    "CSV export",
    status == 200
    and head.get("Content-Type", "").startswith("text/csv")
    and b"Branch,Class" in csv,
    status,
)
_, student_tokens = sign_in("student1.madhapur")
_, student_me, _ = call("GET", "/api/v1/me/", token=student_tokens["access"])
status, report, _ = call(
    "GET", f"/api/v1/students/{student_me['student_id']}/report/", token=student_tokens["access"]
)
check("student reads their own report", status == 200 and "results" in report, status)
check(
    "published results carry grades from scale v1",
    report["results"]
    and all(r["grade"] for r in report["results"] if not r["absent"])
    and report["summary"]["grade"],
)
status, _, _ = call(
    "GET",
    f"/api/v1/students/{student_me['student_id'] + 1}/report/",
    token=student_tokens["access"],
)
check("student cannot read another student's report (404)", status == 404, status)
status, _, _ = call("GET", "/api/v1/dashboard/", token=student_tokens["access"])
check("student has no dashboard (403)", status == 403, status)
status, activity, _ = call(
    "GET", "/api/v1/activity/?action=exam.", token=principal_tokens["access"]
)
check(
    "activity log shows the workflow",
    status == 200 and {"exam.submit", "exam.publish"} <= {e["action"] for e in activity["results"]},
)

# 8. Phase 3: parents, leave, notifications, report cards.
status, parent_tokens = sign_in("parent1.madhapur")
check("parent signs in", status == 200, status)
parent = parent_tokens["access"]
_, parent_me, _ = call("GET", "/api/v1/me/", token=parent)
children = parent_me["children"]
check(
    "/me/ lists the parent's child", [c["name"] for c in children] and parent_me["role"] == "parent"
)
child_id = children[0]["student_id"]
status, card, head = call(
    "GET", f"/api/v1/students/{child_id}/report-card/", token=parent, accept="application/pdf"
)
check("parent downloads the report card PDF", status == 200 and card[:4] == b"%PDF", status)
status, _, _ = call("GET", "/api/v1/students/", token=parent)
check("parents can't list students (403)", status == 403, status)
start = date.today() + timedelta(days=10)
status, leave, _ = call(
    "POST",
    "/api/v1/leave-requests/",
    {
        "student": child_id,
        "starts_on": start.isoformat(),
        "ends_on": start.isoformat(),
        "reason": "API end-to-end check",
    },
    token=parent,
)
check(
    "parent applies for leave",
    status == 201 and leave["status"] == "pending",
    leave if status != 201 else "",
)
status, _, _ = call("POST", f"/api/v1/leave-requests/{leave['id']}/approve/", token=parent)
check("parent can't approve their own request (403)", status == 403, status)
_, teacher_tokens2 = sign_in("teacher.madhapur")
teacher2 = teacher_tokens2["access"]


def teacher_was_told():
    _, bell, _ = call("GET", "/api/v1/notifications/?unread=true&kind=leave", token=teacher2)
    return any("Leave request" in n["title"] for n in bell["results"])


check("class teacher was notified of the request", eventually(teacher_was_told))
status, decided, _ = call("POST", f"/api/v1/leave-requests/{leave['id']}/approve/", token=teacher2)
check("class teacher approves", status == 200 and decided["status"] == "approved", status)


def parent_was_told():
    _, parent_bell, _ = call("GET", "/api/v1/notifications/?kind=leave", token=parent)
    return any("approved" in n["title"] for n in parent_bell["results"])


check("parent's bell has the decision", eventually(parent_was_told))
_, news, _ = call("GET", "/api/v1/announcements/", token=parent)
check(
    "parent sees announcements meant for parents",
    any(a["audience"] == "parents" for a in news["results"]),
)
_, dash, _ = call("GET", "/api/v1/dashboard/", token=principal_tokens["access"])
check(
    "principal dashboard has the 30-day trend",
    len(dash["attendance_trend"]) > 0 and "low_attendance" in dash,
)

# 9. Phase 4: fees, with the accountant handling money and nothing academic.
status, accountant_tokens = sign_in("accountant.madhapur")
accountant = accountant_tokens["access"]
for path in (
    "/api/v1/exams/",
    "/api/v1/students/",
    "/api/v1/dashboard/",
    "/api/v1/timetable/mine/",
):
    status, _, _ = call("GET", path, token=accountant)
    check(f"accountant gets 403 on {path}", status == 403, status)
_, family_invoices, _ = call("GET", "/api/v1/invoices/?status=issued", token=parent)
open_invoice = family_invoices["results"][0]
status, payment, _ = call(
    "POST",
    f"/api/v1/invoices/{open_invoice['id']}/payment/",
    {"amount_paise": 50000, "method": "upi", "reference": "UPI-E2E-1"},
    token=accountant,
)
check(
    "accountant records a UPI payment with a receipt",
    status == 201 and payment["receipt_number"].startswith("MDP/"),
    payment if status != 201 else "",
)


def parent_got_receipt():
    _, bell, _ = call("GET", "/api/v1/notifications/?kind=fees", token=parent)
    return any(payment["receipt_number"] in n["body"] for n in bell["results"])


check("parent is notified of the payment (background job)", eventually(parent_got_receipt))
_, plans, _ = call("GET", "/api/v1/fee-plans/", token=accountant)
check(
    "fee plans show grade and grade_id",
    plans["results"] and isinstance(plans["results"][0]["grade_id"], int),
)

# 10. Phase 5: terms, timetable, promotion preview, CSV import, request ids.
_, super_tokens = sign_in("superadmin")
root = super_tokens["access"]
_, years, _ = call("GET", "/api/v1/years/", token=root)
year_id = years["results"][0]["id"]
_, terms, _ = call("GET", f"/api/v1/years/{year_id}/terms/", token=root)
check("the year has two terms", [t["name"] for t in terms["terms"]] == ["Term 1", "Term 2"])
status, saved_terms, _ = call(
    "PUT", f"/api/v1/years/{year_id}/terms/", {"terms": terms["terms"]}, token=root
)
check(
    "super admin saves the terms back unchanged",
    status == 200 and len(saved_terms["terms"]) == 2,
    status,
)
status, _, _ = call(
    "PUT", f"/api/v1/years/{year_id}/terms/", {"terms": terms["terms"]}, token=admin
)
check("branch admins can't change terms (403)", status == 403, status)
_, scales, _ = call("GET", "/api/v1/grading-scales/", token=teacher2)
check(
    "grading scale v1 with the CBSE bands",
    scales["results"][0]["version"] == 1 and scales["results"][0]["bands"][0]["label"] == "A1",
)
_, week, _ = call("GET", f"/api/v1/classrooms/{homeroom['id']}/timetable/", token=teacher2)
check(
    "a class has a full week (6 days x 6 periods)",
    len(week["lessons"]) == 36 and len(week["periods"]) == 6,
    len(week["lessons"]),
)
status, mine, _ = call("GET", "/api/v1/timetable/mine/", token=teacher2)
check("the teacher's own week", status == 200 and len(mine) > 0, status)
_, all_classes, _ = call("GET", "/api/v1/classrooms/?page_size=100", token=admin)
other = next(
    c
    for c in all_classes["results"]
    if c["id"] != homeroom["id"] and c["branch"]["id"] == homeroom["branch"]["id"]
)
first_lesson = week["lessons"][0]
_, assignments, _ = call(
    "GET",
    f"/api/v1/assignments/?classroom={other['id']}&teacher={first_lesson['teacher']['id']}",
    token=admin,
)
if assignments["results"]:
    clash = {
        "weekday": first_lesson["weekday"],
        "period": first_lesson["period"]["id"],
        "assignment": assignments["results"][0]["id"],
    }
    status, body, _ = call(
        "POST", f"/api/v1/classrooms/{other['id']}/timetable/", clash, token=admin
    )
    check(
        "booking a busy teacher into another class is refused (400)",
        status == 400 and "already teaches" in body["detail"],
        body,
    )
status, preview, _ = call(
    "GET", f"/api/v1/classrooms/{homeroom['id']}/promotion/", token=principal_tokens["access"]
)
check(
    "principal previews the year-end promotion",
    status == 200 and preview and preview[0]["default"] in ("promote", "leave"),
    status,
)
status, _, _ = call("GET", f"/api/v1/classrooms/{homeroom['id']}/promotion/", token=teacher2)
check("teachers can't promote (403)", status == 403, status)

joined = (date.today() + timedelta(days=1)).isoformat()  # today's register is already saved
grade_label = f"{homeroom['grade']}-{homeroom['section']}"
csv_bytes = (
    "admission_number,first_name,last_name,email,classroom,joined_on,guardian_first_name,guardian_last_name,guardian_email,relationship\n"
    f"API-IMP-1,Api,Import,api.import@example.invalid,{grade_label},{joined},Gita,Import,gita.import@example.invalid,mother\n"
).encode()
raw, content_type = multipart(
    {"branch": homeroom["branch"]["id"], "year": year_id}, {"file": ("students.csv", csv_bytes)}
)
status, batch, head = call(
    "POST", "/api/v1/student-imports/", raw=raw, content_type=content_type, token=admin
)
check("admin uploads a CSV: checked, nothing imported yet", status == 201 and batch["ready"], batch)
upload_request = head.get("X-Request-ID")
status, done, _ = call("POST", f"/api/v1/student-imports/{batch['id']}/confirm/", token=admin)
check(
    "confirming imports the student and the guardian",
    status == 200 and done["status"] == "imported" and len(done["accounts"]) == 2,
    done,
)
status, again, _ = call("POST", f"/api/v1/student-imports/{batch['id']}/confirm/", token=admin)
check("confirming twice imports nothing more", again["accounts"] == done["accounts"])


def invites_arrived():
    with urllib.request.urlopen(f"{MAILPIT}/api/v1/messages?limit=500", timeout=10) as r:
        inbox = json.load(r)
    addresses = {to["Address"] for m in inbox["messages"] for to in m["To"]}
    return {"api.import@example.invalid", "gita.import@example.invalid"} <= addresses


check("both new accounts get a set-your-password email (worker)", eventually(invites_arrived))
status, found, _ = call("GET", f"/api/v1/activity/?request_id={upload_request}", token=admin)
check(
    "the activity log finds the upload's entries by request id",
    status == 200 and [e["action"] for e in found["results"]] == ["students.import.checked"],
    found,
)

print(f"\n{len(failures)} failures" if failures else "\nALL API CHECKS PASSED")
sys.exit(1 if failures else 0)
