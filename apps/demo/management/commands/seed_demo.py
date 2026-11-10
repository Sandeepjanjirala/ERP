"""Seed an empty development database with a realistic, synthetic school group.

All records are created through the same services real users go through (create_exam,
save_marks, transition_exam, save_register), so the demo data obeys every business rule and
fills the activity log. A fixed random seed makes names and scores the same on every run.
"""

import random
import secrets
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.academics.models import (
    AcademicYear,
    Classroom,
    Grade,
    Period,
    Subject,
    TeachingAssignment,
    TimetableSlot,
)
from apps.academics.services import default_terms, save_lesson, save_setup_record
from apps.accounts.models import User
from apps.attendance.models import Attendance, LeaveRequest
from apps.attendance.services import decide_leave, request_leave, save_register
from apps.communication.models import Announcement
from apps.communication.services import publish_announcement
from apps.core.jobs import jobs_paused
from apps.exams.models import Exam
from apps.exams.services import (
    DEFAULT_BANDS,
    create_exam,
    save_grading_scale,
    save_marks,
    transition_exam,
)
from apps.fees.models import FeeHead, FeePlan, Invoice, Payment, Receipt
from apps.fees.services import (
    grant_concession,
    issue_invoices,
    record_counter_payment,
    save_fee_head,
    save_fee_plan,
    simulate_sandbox_payment,
    start_online_payment,
)
from apps.organization.models import Branch, Organization
from apps.students.models import Enrollment, Student
from apps.students.services import link_guardian


@dataclass(frozen=True)
class Size:
    classes: int
    students_per_class: int
    subjects: int
    history_days: int


SIZES = {
    "full": Size(classes=5, students_per_class=25, subjects=5, history_days=91),
    "small": Size(classes=2, students_per_class=4, subjects=2, history_days=7),
}

GROUP_NAME = "Greenfield Group of Schools"
GRADES = ["Class 10", "Class 9", "Class 8", "Class 7", "Class 6"]
SUBJECTS = ["Mathematics", "Science", "English", "Social Studies", "Telugu"]
BRANCHES = [
    {
        "code": "madhapur",
        "name": "Madhapur",
        "city": "Hyderabad",
        "admin": ("Kiran", "Rao"),
        "principal": ("Lakshmi", "Devi"),
        "accountant": ("Meena", "Iyer"),
        "receipt_prefix": "MDP",
        # Teacher n teaches SUBJECTS[n] in every class and is class teacher of GRADES[n].
        "teachers": [
            ("teacher", "Priya", "Sharma"),
            ("ravi", "Ravi", "Kumar"),
            ("anita", "Anita", "Desai"),
            ("farhan", "Farhan", "Ali"),
            ("sravani", "Sravani", "Reddy"),
        ],
    },
    {
        "code": "benz-circle",
        "name": "Benz Circle",
        "city": "Vijayawada",
        "admin": ("Suresh", "Babu"),
        "principal": ("Padma", "Rani"),
        "accountant": ("Rajesh", "Gupta"),
        "receipt_prefix": "BZC",
        "teachers": [
            ("teacher", "Venkat", "Rao"),
            ("divya", "Divya", "Menon"),
            ("arjun", "Arjun", "Varma"),
            ("nazia", "Nazia", "Begum"),
            ("mohan", "Mohan", "Krishna"),
        ],
    },
]
FIRST_NAMES = [
    "Aarav", "Ananya", "Ishaan", "Meera", "Rohan", "Saanvi", "Vihaan", "Diya", "Arjun", "Kavya",
    "Aditya", "Isha", "Karthik", "Lakshmi", "Nikhil", "Pooja", "Rahul", "Sneha", "Tarun", "Varsha",
    "Abhinav", "Bhavya", "Charan", "Deepika", "Gautam", "Harini", "Imran", "Jahnavi", "Kiran",
    "Lavanya", "Manish", "Nandini", "Omkar", "Pranavi", "Rithvik", "Sahithi", "Teja", "Usha",
    "Vamsi", "Yamini", "Zoya", "Akhil", "Bindu", "Dhruv", "Esha", "Farhan", "Gayatri", "Hemant",
    "Ira", "Jayant", "Keerthi", "Madhav", "Neha", "Pavan", "Ritu", "Sai", "Tanvi", "Uday", "Vidya",
]  # fmt: skip
LAST_NAMES = [
    "Sharma", "Rao", "Reddy", "Nair", "Kumar", "Patel", "Iyer", "Gupta", "Menon", "Varma",
    "Naidu", "Chowdary", "Pillai", "Joshi", "Das", "Khan", "Mehta", "Bose", "Shetty", "Kulkarni",
    "Agarwal", "Desai", "Hegde", "Prasad", "Murthy", "Sastry", "Goud", "Babu", "Singh", "Ali",
]  # fmt: skip
PARENT_NAMES = {
    "mother": ["Radha", "Sunitha", "Kavitha", "Swathi", "Madhavi", "Aruna", "Shabana", "Geetha"],
    "father": [
        "Srinivas",
        "Ramesh",
        "Prakash",
        "Venkatesh",
        "Naveen",
        "Sanjay",
        "Imtiaz",
        "Mahesh",
    ],
}
# Exam title, maximum marks, pass marks, position in the history window (0 to 1).
EXAMS = [
    ("Unit Test 1", 25, 9, 0.25),
    ("Unit Test 2", 25, 9, 0.55),
    ("Quarterly Exam", 100, 35, 0.9),
]


# Fee heads: name, code and the yearly amount in rupees. Tuition rises with the grade.
FEE_HEADS = [("Tuition", "tuition"), ("Transport", "transport"), ("Exam fee", "exam")]
TUITION_BY_GRADE = {"Class 10": 18000, "Class 9": 16500, "Class 8": 15000, "Class 7": 14000}
TUITION_DEFAULT, TRANSPORT, EXAM_FEE = 13000, 6000, 1500


# The bell schedule: (start, end) of each period, the same in every branch.
PERIODS = [
    (time(8, 30), time(9, 15)),
    (time(9, 20), time(10, 5)),
    (time(10, 10), time(10, 55)),
    (time(11, 10), time(11, 55)),
    (time(12, 0), time(12, 45)),
    (time(13, 30), time(14, 15)),
]


def school_days(start, end):
    """Monday to Saturday, as most Indian schools work."""
    days = (start + timedelta(days=n) for n in range((end - start).days + 1))
    return [day for day in days if day.weekday() != 6]


class Command(BaseCommand):
    help = "Seed an empty development database with a synthetic school group."

    def add_arguments(self, parser):
        parser.add_argument(
            "--size",
            choices=sorted(SIZES),
            default="full",
            help="full: 250 students and about three months of history (default); small: for tests.",
        )

    @transaction.atomic
    def handle(self, *args, size, **options):
        if not settings.DEBUG:
            raise CommandError("Demo seeding is disabled outside development mode.")
        if User.objects.exists() or Branch.objects.exists():
            raise CommandError(
                "Demo seeding requires an empty database. Existing records were not changed."
            )
        self.size = SIZES[size]
        self.rng = random.Random(2026)
        self.password = secrets.token_urlsafe(18)
        # Password hashing is slow on purpose (PBKDF2). All demo accounts share one password, so
        # hash it once instead of 265 times; the seed then takes seconds instead of minutes.
        self.password_hash = make_password(self.password)
        self.today = timezone.localdate()

        org = Organization.objects.create(name=GROUP_NAME)
        superadmin = User.objects.create_superuser(
            "superadmin", "superadmin@example.invalid", self.password, first_name="Sandeep"
        )
        # The CBSE bands as version 1, before any result is published with it.
        save_grading_scale(
            superadmin,
            [{"label": label, "min_percent": minimum} for label, minimum in DEFAULT_BANDS],
        )
        start = self.today.year if self.today.month >= 4 else self.today.year - 1
        self.year = AcademicYear.objects.create(
            name=f"{start}–{start + 1}", starts_on=date(start, 4, 1), ends_on=date(start + 1, 3, 31)
        )
        default_terms(self.year)  # Term 1 from April, Term 2 from October
        self.history_start = max(
            self.year.starts_on, self.today - timedelta(days=self.size.history_days)
        )
        # Every row goes through the real services and model validation, so the data can never
        # break a business rule; the full size takes about 15 seconds (longer in Docker Desktop).
        self.stdout.write("Creating a synthetic school group; the full size takes under a minute.")
        # Months of history are recorded at once: that must not send today's families an alert
        # for every past absence and published result.
        self.branches = []
        with jobs_paused():
            for index, spec in enumerate(BRANCHES, start=1):
                self.seed_branch(org, index, spec)
        self.seed_announcements()

        self.stdout.write(
            self.style.SUCCESS("Synthetic demo data created (all names are fictional).")
        )
        self.stdout.write(
            f"{Student.objects.count()} students, {Classroom.objects.count()} classrooms, "
            f"{Exam.objects.count()} exams, {Attendance.objects.count()} attendance records, "
            f"{Invoice.objects.count()} fee invoices, {Receipt.objects.count()} receipts."
        )
        self.stdout.write("Demo password for all accounts: " + self.password)
        self.stdout.write(
            "Logins: superadmin, admin.madhapur, principal.madhapur, teacher.madhapur, "
            "accountant.madhapur, student1.madhapur, parent1.madhapur"
        )
        self.stdout.write(
            "Second branch: admin.benz-circle, principal.benz-circle, teacher.benz-circle, "
            "accountant.benz-circle, student1.benz-circle, parent1.benz-circle"
        )
        self.stdout.write(
            "The password is generated for this installation; it is not stored in project files."
        )

    def account(self, username, first, last, role, branch):
        user = User(
            username=username,
            email=f"{username}@example.invalid",
            first_name=first,
            last_name=last,
            role=role,
            branch=branch,
            password=self.password_hash,
            must_change_password=False,
        )
        user.save()
        return user

    def seed_branch(self, org, index, spec):
        code, size = spec["code"], self.size
        branch = Branch.objects.create(
            organization=org,
            name=spec["name"],
            code=code,
            city=spec["city"],
            receipt_prefix=spec["receipt_prefix"],
        )
        admin = self.account(f"admin.{code}", *spec["admin"], User.Role.ADMIN, branch)
        accountant = self.account(
            f"accountant.{code}", *spec["accountant"], User.Role.ACCOUNTANT, branch
        )
        principal = self.account(
            f"principal.{code}", *spec["principal"], User.Role.PRINCIPAL, branch
        )
        teachers = [
            self.account(f"{key}.{code}", first, last, User.Role.TEACHER, branch)
            for key, first, last in spec["teachers"][: size.subjects]
        ]
        subjects = [
            Subject.objects.create(branch=branch, name=name, code=name.lower().replace(" ", "-"))
            for name in SUBJECTS[: size.subjects]
        ]
        # Every grade the branch teaches, in order (Class 6 is 6), so promotion knows what is next.
        grades = {
            name: Grade.objects.create(branch=branch, name=name, order=int(name.split()[-1]))
            for name in GRADES
        }
        classrooms = [
            Classroom.objects.create(
                branch=branch,
                year=self.year,
                grade=grades[grade],
                section="A",
                homeroom_teacher=teachers[n % len(teachers)],
            )
            for n, grade in enumerate(GRADES[: size.classes])
        ]
        for classroom in classrooms:
            for teacher, subject in zip(teachers, subjects, strict=True):
                TeachingAssignment.objects.create(
                    teacher=teacher, classroom=classroom, subject=subject
                )

        # Each student gets a steady attendance habit and an underlying ability; about 6% are
        # "at risk" with attendance below 75%.
        number = 0
        roster = {}
        for classroom in classrooms:
            roster[classroom] = []
            for _ in range(size.students_per_class):
                number += 1
                user = self.account(
                    f"student{number}.{code}",
                    self.rng.choice(FIRST_NAMES),
                    self.rng.choice(LAST_NAMES),
                    User.Role.STUDENT,
                    branch,
                )
                student = Student.objects.create(
                    user=user, admission_number=f"GF-{index}{number:03}"
                )
                enrollment = Enrollment.objects.create(
                    student=student,
                    classroom=classroom,
                    year=self.year,
                    joined_on=self.year.starts_on,
                )
                at_risk = self.rng.random() < 0.06
                enrollment.attendance_rate = (
                    self.rng.uniform(0.62, 0.74) if at_risk else self.rng.uniform(0.88, 0.99)
                )
                enrollment.ability = min(max(self.rng.gauss(0.68, 0.13), 0.2), 0.98)
                roster[classroom].append(enrollment)

        self.progress(f"{spec['name']}: {number} students in {len(classrooms)} classes")
        parents = self.seed_families(code, admin, roster)
        self.progress(f"{spec['name']}: {parents} parent accounts")
        self.seed_exams(classrooms, teachers, subjects, roster, principal)
        self.progress(f"{spec['name']}: exams, marks and results")
        self.seed_attendance(classrooms, roster)
        self.progress(f"{spec['name']}: daily registers since {self.history_start:%d %b}")
        self.seed_leave(roster)
        self.seed_fees(branch, admin, accountant, classrooms)
        self.seed_timetable(branch, admin, classrooms)
        self.progress(f"{spec['name']}: periods and weekly timetables")
        self.progress(f"{spec['name']}: fee invoices, payments and receipts")
        self.branches.append((branch, principal, teachers[0], classrooms[0]))

    def seed_families(self, code, admin, roster):
        """A parent account for every student; about one family in ten has two children here.

        Logins are created like the other demo accounts (one shared, pre-hashed password); each
        link goes through link_guardian, as an admin would make it.
        """
        parents = 0
        previous = None
        enrollments = [e for students in roster.values() for e in students]
        for number, enrollment in enumerate(enrollments, start=1):
            student = enrollment.student
            if previous and self.rng.random() < 0.1:
                # A brother or sister of the previous student: same family, same surname.
                parent, relationship = previous
                student.user.last_name = parent.last_name
                student.user.save(update_fields=["last_name"])
            else:
                relationship = self.rng.choice(["mother", "father"])
                parent = self.account(
                    f"parent{number}.{code}",
                    self.rng.choice(PARENT_NAMES[relationship]),
                    student.user.last_name,
                    User.Role.PARENT,
                    student.user.branch,
                )
                parents += 1
            link_guardian(admin, student, parent, relationship)
            previous = (parent, relationship)
        return parents

    def seed_fees(self, branch, admin, accountant, classrooms):
        """Fee heads and a plan per grade; Term 1 (now overdue) and Term 2 (due soon) invoices.

        About 70% of Term 1 is paid in full and 15% in part, at the counter or online (through
        the Sandbox, so the signed-webhook path runs), leaving some invoices overdue. Each payment
        is then dated inside the term, so the history and the collection report look real.
        """
        heads = {
            code: save_fee_head(admin, FeeHead(branch=branch, name=name, code=code))
            for name, code in FEE_HEADS
        }
        span = (self.today - self.history_start).days
        term1_due = self.history_start + timedelta(days=min(20, max(span - 1, 0)))
        for classroom in classrooms:
            plan = save_fee_plan(
                admin,
                FeePlan(branch=branch, year=self.year, grade=classroom.grade),
                {
                    heads["tuition"]: TUITION_BY_GRADE.get(classroom.grade.name, TUITION_DEFAULT)
                    * 100,
                    heads["transport"]: TRANSPORT * 100,
                    heads["exam"]: EXAM_FEE * 100,
                },
            )
            term1, _ = issue_invoices(
                accountant, plan, "Term 1 fees", term1_due, issued_on=self.history_start
            )
            issue_invoices(accountant, plan, "Term 2 fees", self.today + timedelta(days=21))
            for invoice in term1:
                roll = self.rng.random()
                if roll < 0.7:
                    amount = invoice.balance_paise
                elif roll < 0.85:
                    amount = invoice.balance_paise // 2
                else:
                    continue  # unpaid: overdue
                if self.rng.random() < 0.25:
                    parent = invoice.student.guardian_links.get(is_primary=True).guardian.user
                    simulate_sandbox_payment(
                        parent, start_online_payment(parent, invoice), "captured"
                    )
                    payment = invoice.payments.get()
                else:
                    method = self.rng.choice(["cash", "cash", "upi", "cheque"])
                    reference = "" if method == "cash" else f"REF{self.rng.randint(100000, 999999)}"
                    payment = record_counter_payment(accountant, invoice, amount, method, reference)
                paid_on = self.history_start + timedelta(days=self.rng.randint(0, span))
                Payment.objects.filter(pk=payment.pk).update(
                    paid_at=timezone.make_aware(datetime.combine(paid_on, time(10, 30)))
                )
        # One sibling concession per branch, on a Term 2 invoice, granted by the branch admin.
        invoice = Invoice.objects.filter(branch=branch, title="Term 2 fees").order_by("pk").first()
        if invoice:
            grant_concession(admin, invoice, 100000, "Sibling discount")

    def seed_timetable(self, branch, admin, classrooms):
        """Each branch's periods, and a full week for every class through save_lesson (so the
        clash rules apply). Subjects rotate by period, day and class: with one teacher per
        subject, no teacher is ever in two classes at once."""
        periods = [
            save_setup_record(
                admin, "period", Period(branch=branch, number=n, starts_at=starts, ends_at=ends)
            )
            for n, (starts, ends) in enumerate(PERIODS, start=1)
        ]
        for index, classroom in enumerate(classrooms):
            teaching = list(classroom.teaching.select_related("subject").order_by("subject__name"))
            for day in TimetableSlot.Day.values:
                for number, period in enumerate(periods):
                    assignment = teaching[(number + day + index) % len(teaching)]
                    save_lesson(admin, classroom, day, period, assignment)

    def seed_leave(self, roster):
        """A few leave requests per branch: one approved (it excuses recorded absences), one
        refused, and one waiting for the class teacher."""
        enrollments = [e for students in roster.values() for e in students]
        yesterday = self.today - timedelta(days=1)
        plans = [
            (yesterday - timedelta(days=1), yesterday, "Fever", True),
            (
                self.today + timedelta(days=3),
                self.today + timedelta(days=4),
                "Family wedding",
                False,
            ),
            (self.today + timedelta(days=1), self.today + timedelta(days=1), "Doctor visit", None),
        ]
        picks = self.rng.sample(enrollments, k=min(len(plans), len(enrollments)))
        for enrollment, (starts, ends, reason, approve) in zip(picks, plans, strict=False):
            student = enrollment.student
            parent = student.guardian_links.get(is_primary=True).guardian.user
            leave = request_leave(
                parent,
                LeaveRequest(student=student, starts_on=starts, ends_on=ends, reason=reason),
            )
            if approve is not None:
                decide_leave(
                    enrollment.classroom.homeroom_teacher,
                    leave,
                    approve,
                    "" if approve else "Half-yearly exams that week. Please choose other days.",
                )

    def seed_announcements(self):
        """A few announcements, delivered for real (not paused), so bells have something in them."""
        publish_announcement(
            User.objects.get(username="superadmin"),
            Announcement(
                audience=Announcement.Audience.EVERYONE,
                title="Welcome to EduNexa",
                body="Attendance, results, report cards and announcements are now online. "
                "Parents can also apply for leave here.",
            ),
        )
        for branch, principal, teacher, classroom in self.branches:
            publish_announcement(
                principal,
                Announcement(
                    branch=branch,
                    audience=Announcement.Audience.PARENTS,
                    title="Parent-teacher meeting on Saturday",
                    body="Meet your child's class teacher between 9 am and 12 noon.",
                ),
            )
            publish_announcement(
                teacher,
                Announcement(
                    branch=branch,
                    audience=Announcement.Audience.CLASS,
                    classroom=classroom,
                    title="Science fair projects",
                    body="Please bring your project models to class on Monday.",
                ),
            )

    def progress(self, message):
        self.stdout.write(f"  {message}")
        self.stdout.flush()

    def seed_exams(self, classrooms, teachers, subjects, roster, principal):
        span = (self.today - self.history_start).days
        for classroom in classrooms:
            for position, (teacher, subject) in enumerate(zip(teachers, subjects, strict=True)):
                difficulty = self.rng.uniform(-0.06, 0.06)
                for title, max_marks, pass_marks, at in EXAMS:
                    exam = create_exam(
                        teacher,
                        Exam(
                            classroom=classroom,
                            subject=subject,
                            title=title,
                            date=self.history_start + timedelta(days=round(span * at)),
                            max_marks=max_marks,
                            pass_marks=pass_marks,
                        ),
                    )
                    entries = {}
                    for enrollment in roster[classroom]:
                        if self.rng.random() < 0.02:
                            entries[enrollment.pk] = (None, True)
                            continue
                        share = enrollment.ability + difficulty + self.rng.gauss(0, 0.07)
                        score = round(max_marks * min(max(share, 0), 1))
                        entries[enrollment.pk] = (Decimal(score), False)
                    save_marks(teacher, exam, entries, exam.version)
                    exam.refresh_from_db()
                    # Unit tests are published. The quarterly exam is mid-workflow: every other
                    # subject awaits the principal's approval, the rest are still drafts.
                    if title == "Quarterly Exam" and position % 2:
                        continue
                    transition_exam(teacher, exam, "submit", exam.version)
                    if title != "Quarterly Exam":
                        exam.refresh_from_db()
                        transition_exam(principal, exam, "publish", exam.version)

    def seed_attendance(self, classrooms, roster):
        for classroom in classrooms:
            for day in school_days(self.history_start, self.today):
                statuses = {}
                for enrollment in roster[classroom]:
                    roll = self.rng.random()
                    if roll > enrollment.attendance_rate:
                        statuses[enrollment.pk] = Attendance.Status.ABSENT
                    elif roll > enrollment.attendance_rate - 0.03:
                        statuses[enrollment.pk] = Attendance.Status.LATE
                    elif roll > enrollment.attendance_rate - 0.04:
                        statuses[enrollment.pk] = Attendance.Status.EXCUSED
                    else:
                        statuses[enrollment.pk] = Attendance.Status.PRESENT
                save_register(classroom.homeroom_teacher, classroom, day, statuses, 0)
