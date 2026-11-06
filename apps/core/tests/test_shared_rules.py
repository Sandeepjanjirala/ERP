"""Rules that the web pages and the API both rely on, checked at the service layer.

These rules used to live in forms and views. They now live in policies and services, so a
request that skips the web form (an API call, a script) still can't get around them.
"""

from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError

from apps.academics.models import AcademicYear, Subject, TeachingAssignment
from apps.academics.services import save_setup_record, update_setup_record
from apps.accounts.models import User
from apps.accounts.policies import staff_roles_for
from apps.accounts.services import change_password, create_account
from apps.attendance.services import register_date_error
from apps.core.testing import PASSWORD, SchoolTestCase
from apps.exams.models import Exam
from apps.exams.policies import can_create_exam
from apps.exams.services import create_exam
from apps.organization.models import Branch
from apps.students.models import Enrollment, Student
from apps.students.services import admit_student, enroll


class AccountRuleTests(SchoolTestCase):
    def new_user(self, role, branch, name="newperson"):
        return User(username=name, email=f"{name}@example.com", role=role, branch=branch)

    def test_staff_roles_each_actor_may_create(self):
        self.assertEqual(
            staff_roles_for(self.root),
            (User.Role.ADMIN, User.Role.PRINCIPAL, User.Role.TEACHER),
        )
        self.assertEqual(staff_roles_for(self.admin), (User.Role.TEACHER,))
        for actor in (self.principal, self.teacher, self.e1.student.user):
            with self.subTest(actor=actor.username):
                self.assertEqual(staff_roles_for(actor), ())

    def test_branch_admin_cannot_create_a_principal_or_another_branchs_teacher(self):
        for person in (
            self.new_user(User.Role.PRINCIPAL, self.a),
            self.new_user(User.Role.TEACHER, self.b),
        ):
            with self.subTest(role=person.role, branch=person.branch.code):
                with self.assertRaises(PermissionDenied):
                    create_account(self.admin, person, PASSWORD)
        self.assertFalse(User.objects.filter(username="newperson").exists())

    def test_weak_password_is_rejected_by_the_service(self):
        with self.assertRaises(ValidationError):
            create_account(self.admin, self.new_user(User.Role.TEACHER, self.a), "short")
        self.assertFalse(User.objects.filter(username="newperson").exists())

    def test_change_password_checks_the_current_one_and_ends_the_forced_change(self):
        self.teacher.must_change_password = True
        self.teacher.save()
        with self.assertRaises(ValidationError):
            change_password(self.teacher, "wrong-password", "A-new-testing-passphrase-94302!")
        change_password(self.teacher, PASSWORD, "A-new-testing-passphrase-94302!")
        self.teacher.refresh_from_db()
        self.assertFalse(self.teacher.must_change_password)
        self.assertTrue(self.teacher.check_password("A-new-testing-passphrase-94302!"))


class ExamCreationRuleTests(SchoolTestCase):
    def draft(self, classroom, subject):
        return Exam(
            classroom=classroom,
            subject=subject,
            title="Unit test",
            date=self.today,
            max_marks=20,
            pass_marks=8,
        )

    def test_who_may_create_an_exam(self):
        cases = [
            (self.root, self.foreign_class, self.foreign_subject, True),
            (self.admin, self.c, self.science, True),
            (self.admin, self.foreign_class, self.foreign_subject, False),
            (self.teacher, self.c, self.math, True),  # assigned pair
            (self.teacher, self.c, self.science, False),  # someone else's subject
            (self.principal, self.c, self.math, False),
            (self.e1.student.user, self.c, self.math, False),
        ]
        for actor, classroom, subject, allowed in cases:
            with self.subTest(actor=actor.username, subject=subject.code):
                self.assertEqual(can_create_exam(actor, classroom, subject), allowed)

    def test_service_refuses_an_unassigned_teacher(self):
        with self.assertRaises(PermissionDenied):
            create_exam(self.teacher, self.draft(self.c, self.science))
        self.assertFalse(Exam.objects.filter(title="Unit test").exists())


class AttendanceDateRuleTests(SchoolTestCase):
    def test_register_dates(self):
        self.assertIsNone(register_date_error(self.c, self.today))
        self.assertIn("Future", register_date_error(self.c, self.today + timedelta(days=1)))
        self.assertIn(
            "academic year", register_date_error(self.c, self.year.starts_on - timedelta(days=1))
        )


class SetupRuleTests(SchoolTestCase):
    def test_who_may_save_setup_records(self):
        cases = [
            # (actor, kind, record, allowed)
            (
                self.root,
                "year",
                AcademicYear(
                    name="Y2", starts_on=self.today, ends_on=self.today + timedelta(days=200)
                ),
                True,
            ),
            (
                self.admin,
                "year",
                AcademicYear(
                    name="Y3", starts_on=self.today, ends_on=self.today + timedelta(days=200)
                ),
                False,
            ),
            (self.admin, "branch", Branch(name="East", code="east", city="Guntur"), False),
            (self.admin, "subject", Subject(branch=self.a, name="History", code="history"), True),
            (self.admin, "subject", Subject(branch=self.b, name="History", code="history"), False),
            (self.principal, "subject", Subject(branch=self.a, name="Art", code="art"), False),
            (self.root, "subject", Subject(branch=self.b, name="Art", code="art"), True),
        ]
        for actor, kind, record, allowed in cases:
            with self.subTest(actor=actor.username, kind=kind, record=str(record)):
                if allowed:
                    save_setup_record(actor, kind, record)
                    self.assertIsNotNone(record.pk)
                else:
                    with self.assertRaises(PermissionDenied):
                        save_setup_record(actor, kind, record)
                    self.assertIsNone(record.pk)

    def test_edits_are_checked_against_the_records_branch(self):
        assignment = TeachingAssignment.objects.get(subject=self.foreign_subject)
        assignment.teacher = self.foreign_teacher
        with self.assertRaises(PermissionDenied):
            update_setup_record(self.admin, "assignment", assignment, str(assignment), ["teacher"])


class EnrollmentRuleTests(SchoolTestCase):
    def test_enrollment_year_always_comes_from_the_classroom(self):
        student = Student.objects.create(
            user=User.objects.create_user(
                "dana", "dana@example.com", PASSWORD, role="student", branch=self.a
            ),
            admission_number="DANA",
        )
        enrollment = enroll(
            self.admin,
            Enrollment(student=student, classroom=self.c, joined_on=self.today),
        )
        self.assertEqual(enrollment.year, self.c.year)

    def test_only_managers_of_the_branch_may_enroll_or_admit(self):
        student = self.e1.student
        for actor in (self.principal, self.teacher, self.foreign_teacher):
            with self.subTest(actor=actor.username):
                with self.assertRaises(PermissionDenied):
                    enroll(
                        actor, Enrollment(student=student, classroom=self.c, joined_on=self.today)
                    )
        new_user = User(username="eve", email="eve@example.com", role="student", branch=self.b)
        with self.assertRaises(PermissionDenied):  # a branch admin, but not of South
            admit_student(self.admin, new_user, PASSWORD, "EVE", self.foreign_class, self.today)
        self.assertFalse(User.objects.filter(username="eve").exists())
