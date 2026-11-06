"""Lists must cost the same number of SQL queries whether they show 3 rows or 13 (no N+1).

Built with factory_boy factories, so each test creates exactly the rows it needs. Each endpoint
is measured in its own test (a fresh database) and with one page big enough for every row, so
pagination can't hide a query that runs once per row.
"""

from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.academics.tests.factories import (
    ClassroomFactory,
    SubjectFactory,
    TeachingAssignmentFactory,
)
from apps.accounts.models import User
from apps.accounts.tests.factories import UserFactory
from apps.audit.services import audit
from apps.exams.tests.factories import ExamFactory
from apps.students.tests.factories import EnrollmentFactory


class FactoryTests(TestCase):
    def test_factories_build_consistent_records(self):
        enrollment = EnrollmentFactory()
        # Every model validates itself on save, so creating them at all proves they're valid.
        self.assertEqual(enrollment.student.user.branch, enrollment.classroom.branch)
        self.assertEqual(enrollment.year, enrollment.classroom.year)
        self.assertEqual(enrollment.classroom.homeroom_teacher.branch, enrollment.classroom.branch)
        assignment = TeachingAssignmentFactory()
        self.assertEqual(assignment.teacher.branch, assignment.subject.branch)


class QueryCountTests(TestCase):
    client_class = APIClient

    def setUp(self):
        cache.clear()
        self.classroom = ClassroomFactory()
        self.branch, self.year = self.classroom.branch, self.classroom.year
        self.subject = SubjectFactory(branch=self.branch)
        self.admin = UserFactory(role=User.Role.ADMIN, branch=self.branch)
        self.client.force_authenticate(self.admin)

    def queries(self, url):
        with CaptureQueriesContext(connection) as context:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.content)
        return len(context)

    def assert_constant(self, url, grow, first=2, then=10):
        grow(first)
        few = self.queries(url)
        grow(then)
        self.assertEqual(self.queries(url), few, f"{url} runs more queries as rows grow")

    # How each list grows.
    def students(self, n):
        EnrollmentFactory.create_batch(n, classroom=self.classroom)

    def classrooms(self, n):
        ClassroomFactory.create_batch(n, branch=self.branch, year=self.year)

    def test_students(self):
        self.assert_constant("/api/v1/students/?page_size=100", self.students)

    def test_enrollments(self):
        self.assert_constant("/api/v1/enrollments/?page_size=100", self.students)

    def test_people(self):
        self.assert_constant("/api/v1/people/?page_size=100", self.students)

    def test_exams(self):
        def exams(n):
            ExamFactory.create_batch(n, classroom=self.classroom, subject=self.subject)

        self.assert_constant("/api/v1/exams/?page_size=100", exams)

    def test_classrooms(self):
        self.assert_constant("/api/v1/classrooms/?page_size=100", self.classrooms)

    def test_assignments(self):
        def assignments(n):
            for classroom in ClassroomFactory.create_batch(n, branch=self.branch, year=self.year):
                TeachingAssignmentFactory(classroom=classroom)

        self.assert_constant("/api/v1/assignments/?page_size=100", assignments)

    def test_activity(self):
        def events(n):
            for i in range(n):
                audit(self.admin, self.branch, "test.event", f"event {i}")

        self.assert_constant("/api/v1/activity/?page_size=100", events)

    def test_dashboard(self):
        # The dashboard lists up to 12 classes: 1 + 2 + 8 = 11 stays under that cap.
        self.assert_constant("/api/v1/dashboard/", self.classrooms, first=2, then=8)

    def test_register_and_mark_sheet(self):
        """These list the whole class, so their cost must not depend on the class size."""
        self.assert_constant(f"/api/v1/classrooms/{self.classroom.pk}/register/", self.students)
        exam = ExamFactory(classroom=self.classroom, subject=self.subject)
        self.assert_constant(f"/api/v1/exams/{exam.pk}/marks/", self.students)
