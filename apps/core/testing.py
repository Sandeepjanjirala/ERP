"""Shared test fixtures. Test code may import from any app; the layering rule is for app code."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from unittest import skipUnless

from django.core.cache import cache
from django.db import close_old_connections, connection, connections
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.academics.models import AcademicYear, Classroom, Subject, TeachingAssignment
from apps.accounts.models import User
from apps.core.exceptions import Conflict
from apps.exams.models import Exam
from apps.exams.services import save_marks, transition_exam
from apps.organization.models import Branch, Organization
from apps.students.models import Enrollment, Guardian, Student, StudentGuardian

PASSWORD = "Testing-only-strong-password-892!"


class SchoolTestCase(TestCase):
    """Two branches, staff in every role, two students in one class, a parent, and three exams."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Test Organisation")
        cls.a = Branch.objects.create(
            organization=cls.org, name="North", code="north", city="Hyderabad"
        )
        cls.b = Branch.objects.create(
            organization=cls.org, name="South", code="south", city="Vijayawada"
        )
        cls.today = timezone.localdate()
        cls.year = AcademicYear.objects.create(
            name="Test year",
            starts_on=cls.today - timedelta(days=90),
            ends_on=cls.today + timedelta(days=90),
        )
        cls.root = User.objects.create_superuser("root", "root@example.com", PASSWORD)

        def user(name, role, branch):
            return User.objects.create_user(
                name,
                name + "@example.com",
                PASSWORD,
                role=role,
                branch=branch,
                first_name=name,
                must_change_password=False,
            )

        cls.admin = user("admin", "admin", cls.a)
        cls.principal = user("principal", "principal", cls.a)
        cls.teacher = user("teacher", "teacher", cls.a)
        cls.other_teacher = user("otherteacher", "teacher", cls.a)
        cls.foreign_teacher = user("foreignteacher", "teacher", cls.b)
        cls.c = Classroom.objects.create(
            branch=cls.a, year=cls.year, grade="9", section="A", homeroom_teacher=cls.teacher
        )
        cls.foreign_class = Classroom.objects.create(
            branch=cls.b,
            year=cls.year,
            grade="9",
            section="B",
            homeroom_teacher=cls.foreign_teacher,
        )
        cls.math = Subject.objects.create(branch=cls.a, name="Mathematics", code="math")
        cls.science = Subject.objects.create(branch=cls.a, name="Science", code="science")
        cls.foreign_subject = Subject.objects.create(
            branch=cls.b, name="South Science", code="science"
        )
        TeachingAssignment.objects.create(teacher=cls.teacher, classroom=cls.c, subject=cls.math)
        TeachingAssignment.objects.create(
            teacher=cls.other_teacher, classroom=cls.c, subject=cls.science
        )
        TeachingAssignment.objects.create(
            teacher=cls.foreign_teacher, classroom=cls.foreign_class, subject=cls.foreign_subject
        )

        def enroll(name, branch, classroom):
            u = user(name, "student", branch)
            s = Student.objects.create(user=u, admission_number=name.upper())
            return Enrollment.objects.create(
                student=s, classroom=classroom, year=cls.year, joined_on=cls.year.starts_on
            )

        cls.e1 = enroll("alice", cls.a, cls.c)
        cls.e2 = enroll("bob", cls.a, cls.c)
        cls.foreign_enrollment = enroll("charlie", cls.b, cls.foreign_class)
        # Alice's mother. Bob has no guardian account.
        cls.parent = user("parent", "parent", cls.a)
        StudentGuardian.objects.create(
            student=cls.e1.student,
            guardian=Guardian.objects.create(user=cls.parent),
            relationship=StudentGuardian.Relationship.MOTHER,
            is_primary=True,
        )
        cls.exam = Exam.objects.create(
            classroom=cls.c,
            subject=cls.math,
            title="Midterm",
            date=cls.today,
            max_marks=100,
            pass_marks=35,
        )
        cls.science_exam = Exam.objects.create(
            classroom=cls.c,
            subject=cls.science,
            title="Science test",
            date=cls.today,
            max_marks=50,
            pass_marks=20,
        )
        cls.foreign_exam = Exam.objects.create(
            classroom=cls.foreign_class,
            subject=cls.foreign_subject,
            title="Private south exam",
            date=cls.today,
            max_marks=100,
            pass_marks=35,
        )

    def setUp(self):
        super().setUp()
        # The cache outlives each test's rolled-back database, so start every test empty.
        cache.clear()

    def sign_in(self, user):
        self.client.force_login(user)

    def fill(self, exam=None):
        exam = exam or self.exam
        exam.refresh_from_db()
        save_marks(
            self.teacher,
            exam,
            {self.e1.pk: (Decimal("80"), False), self.e2.pk: (Decimal("30"), False)},
            exam.version,
        )
        exam.refresh_from_db()
        return exam

    def publish(self):
        exam = self.fill()
        transition_exam(self.teacher, exam, "submit", exam.version)
        exam.refresh_from_db()
        transition_exam(self.principal, exam, "publish", exam.version)
        exam.refresh_from_db()
        return exam


class ApiTestCase(SchoolTestCase):
    """SchoolTestCase with DRF's test client, which sends and parses JSON."""

    client_class = APIClient

    def as_user(self, user):
        """Authenticate every following request as `user`, skipping the token round trip."""
        self.client.force_authenticate(user)

    def sign_in_api(self, user, password=PASSWORD):
        """Real sign-in through POST /api/v1/auth/token/; returns the token pair."""
        response = self.client.post(
            "/api/v1/auth/token/", {"username": user.username, "password": password}
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def bearer(self, access):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")


@skipUnless(
    connection.vendor == "postgresql",
    "Requires PostgreSQL row locks; run the provided PostgreSQL CI job or Docker test command.",
)
class ConcurrentTestCase(TransactionTestCase):
    """Real threads and real transactions, so it needs PostgreSQL row locks."""

    def setUp(self):
        SchoolTestCase.setUpTestData.__func__(type(self))

    def race(self, operation):
        barrier = Barrier(2)

        def worker(index):
            close_old_connections()
            try:
                actor = User.objects.get(pk=self.teacher.pk)
                barrier.wait(timeout=10)
                try:
                    operation(actor, index)
                    return "saved"
                except Conflict:
                    return "conflict"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker, index) for index in range(2)]
            results = [f.result(timeout=30) for f in futures]
        self.assertEqual(sorted(results), ["conflict", "saved"])
