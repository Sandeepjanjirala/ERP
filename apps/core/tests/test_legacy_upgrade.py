import json
import tempfile
from io import StringIO
from pathlib import Path

from django.contrib.auth import authenticate
from django.contrib.auth.hashers import make_password
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.academics.models import Classroom
from apps.accounts.models import User
from apps.attendance.models import Attendance
from apps.core.management.commands.convert_legacy_data import convert
from apps.exams.models import Exam
from apps.students.models import Enrollment

PASSWORD = "Legacy-account-password-5521!"


def legacy_export():
    """A small export in the old single-app format (`dumpdata school`)."""
    return [
        {"model": "school.organization", "pk": 1, "fields": {"name": "Old School Group"}},
        {"model": "school.branch", "pk": 7, "fields": {"organization": 1, "name": "North", "code": "north", "city": "Hyderabad"}},
        {"model": "school.user", "pk": 40, "fields": {"password": make_password(PASSWORD), "last_login": None, "is_superuser": False, "username": "teacher.north", "first_name": "Asha", "last_name": "Rao", "email": "asha@example.com", "is_staff": False, "is_active": True, "date_joined": "2026-04-01T09:00:00Z", "role": "teacher", "branch": 7, "must_change_password": False, "groups": [], "user_permissions": []}},
        {"model": "school.user", "pk": 41, "fields": {"password": "!", "last_login": None, "is_superuser": False, "username": "pupil.north", "first_name": "Ravi", "last_name": "K", "email": "ravi@example.com", "is_staff": False, "is_active": True, "date_joined": "2026-04-01T09:00:00Z", "role": "student", "branch": 7, "must_change_password": True, "groups": [], "user_permissions": []}},
        {"model": "school.academicyear", "pk": 3, "fields": {"name": "2026-2027", "starts_on": "2026-04-01", "ends_on": "2027-03-31"}},
        {"model": "school.classroom", "pk": 5, "fields": {"branch": 7, "year": 3, "grade": "Class 9", "section": "A", "homeroom_teacher": 40}},
        {"model": "school.student", "pk": 9, "fields": {"user": 41, "admission_number": "OLD-001"}},
        {"model": "school.enrollment", "pk": 11, "fields": {"student": 9, "classroom": 5, "year": 3, "joined_on": "2026-04-01", "left_on": None}},
        {"model": "school.attendancesession", "pk": 13, "fields": {"classroom": 5, "date": "2026-06-01", "version": 2, "recorded_by": 40, "updated_at": "2026-06-01T10:00:00Z"}},
        {"model": "school.attendance", "pk": 17, "fields": {"session": 13, "enrollment": 11, "status": "L"}},
        {"model": "school.subject", "pk": 21, "fields": {"branch": 7, "name": "Maths", "code": "maths"}},
        {"model": "school.exam", "pk": 23, "fields": {"classroom": 5, "subject": 21, "title": "Unit test", "date": "2026-11-20", "max_marks": "25.00", "pass_marks": "9.00", "status": "published", "version": 2, "published_by": None, "published_at": None}},
        {"model": "school.loginattempt", "pk": "abc", "fields": {"count": 3, "started_at": "2026-06-01T10:00:00Z"}},
    ]  # fmt: skip


class LegacyUpgradeTests(TestCase):
    """Data from the single-app version survives the move to domain apps."""

    def test_records_keep_their_ids_relations_and_passwords(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder, "legacy.json"), Path(folder, "upgraded.json")
            source.write_text(json.dumps(legacy_export()), encoding="utf-8")
            call_command("convert_legacy_data", source, target, stdout=StringIO())
            call_command("loaddata", target, stdout=StringIO())

        teacher = User.objects.get(pk=40)
        self.assertEqual((teacher.username, teacher.branch.code), ("teacher.north", "north"))
        self.assertEqual(authenticate(username="teacher.north", password=PASSWORD), teacher)
        self.assertEqual(Classroom.objects.get(pk=5).homeroom_teacher, teacher)
        self.assertEqual(Enrollment.objects.get(pk=11).student.admission_number, "OLD-001")
        record = Attendance.objects.get(pk=17)
        self.assertEqual((record.status, record.session.version), ("L", 2))
        # Phase 5: the grade text became a Grade, and the exam is in the term of its date.
        classroom = Classroom.objects.get(pk=5)
        self.assertEqual((classroom.grade.name, classroom.grade.order), ("Class 9", 9))
        exam = Exam.objects.get(pk=23)
        self.assertEqual((exam.term.name, exam.status, exam.version), ("Term 2", "published", 2))

    def test_throttle_counters_are_dropped_and_unknown_models_rejected(self):
        converted, counts = convert(legacy_export())
        self.assertNotIn("school.loginattempt", {record["model"] for record in converted})
        self.assertEqual(counts["accounts.user"], 2)
        with self.assertRaises(CommandError):
            convert([{"model": "auth.permission", "pk": 1, "fields": {}}])
