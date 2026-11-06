from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import Count
from django.test import TestCase, override_settings

from apps.accounts.models import User
from apps.attendance.models import AttendanceSession, LeaveRequest
from apps.audit.models import AuditEvent
from apps.communication.models import Announcement, Notification
from apps.exams.models import Exam
from apps.organization.models import Branch, Organization
from apps.students.models import Student, StudentGuardian


class SeedTests(TestCase):
    @override_settings(DEBUG=True)
    def test_seed_generates_synthetic_data_and_wont_overwrite(self):
        out = StringIO()
        call_command("seed_demo", "--size", "small", stdout=out)
        self.assertEqual(Organization.objects.get().name, "Greenfield Group of Schools")
        self.assertEqual(Branch.objects.count(), 2)
        # small: 2 branches x 2 classes x 4 students; 2 subjects with 3 exams each.
        self.assertEqual(Student.objects.count(), 16)
        self.assertEqual(Exam.objects.count(), 24)
        statuses = dict(Exam.objects.values_list("status").annotate(n=Count("id")))
        self.assertEqual(statuses, {"published": 16, "submitted": 4, "draft": 4})
        with self.assertRaises(CommandError):
            call_command("seed_demo", "--size", "small", stdout=out)

    @override_settings(DEBUG=True)
    def test_documented_logins_exist_and_fit_together(self):
        call_command("seed_demo", "--size", "small", stdout=StringIO())
        for username in ("superadmin", "admin.madhapur", "principal.madhapur", "teacher.madhapur"):
            self.assertTrue(User.objects.filter(username=username).exists(), username)
        student = Student.objects.get(user__username="student1.madhapur")
        # The demo teacher is class teacher of the demo student, so both views connect.
        homeroom = student.enrollments.get().classroom.homeroom_teacher
        self.assertEqual(homeroom.username, "teacher.madhapur")

    @override_settings(DEBUG=True)
    def test_registers_are_complete_and_audited(self):
        call_command("seed_demo", "--size", "small", stdout=StringIO())
        sessions = AttendanceSession.objects.annotate(n=Count("records"))
        self.assertTrue(sessions.exists())
        self.assertEqual({session.n for session in sessions}, {4})  # every student, every day
        self.assertEqual(
            AuditEvent.objects.filter(action="attendance.saved").count(), sessions.count()
        )

    @override_settings(DEBUG=False)
    def test_demo_disabled_in_production(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo", stdout=StringIO())

    @override_settings(DEBUG=True)
    def test_families_leave_and_announcements(self):
        with self.captureOnCommitCallbacks(execute=True):
            call_command("seed_demo", "--size", "small", stdout=StringIO())
        # Every student has exactly one primary guardian, and the documented login pairs up.
        primaries = StudentGuardian.objects.filter(is_primary=True)
        self.assertEqual(primaries.count(), Student.objects.count())
        self.assertEqual(primaries.values("student").distinct().count(), Student.objects.count())
        first = StudentGuardian.objects.get(student__user__username="student1.madhapur")
        self.assertEqual(first.guardian.user.username, "parent1.madhapur")

        # Each branch has one approved, one refused and one pending leave request.
        statuses = dict(LeaveRequest.objects.values_list("status").annotate(n=Count("id")))
        self.assertEqual(statuses, {"approved": 2, "rejected": 2, "pending": 2})

        # Announcements were delivered; months of history alerted and emailed nobody.
        self.assertEqual(Announcement.objects.count(), 5)
        kinds = set(Notification.objects.values_list("kind", flat=True))
        self.assertEqual(kinds, {"announcement"})
        self.assertTrue(
            Notification.objects.filter(recipient__username="parent1.madhapur").exists()
        )
        self.assertEqual(mail.outbox, [])
