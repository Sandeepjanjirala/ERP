from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.exams.models import Exam
from apps.organization.models import Branch
from apps.students.models import Student


class SeedTests(TestCase):
    @override_settings(DEBUG=True)
    def test_seed_generates_synthetic_data_and_wont_overwrite(self):
        out = StringIO()
        call_command("seed_demo", stdout=out)
        self.assertEqual(Branch.objects.count(), 2)
        self.assertEqual(Student.objects.count(), 12)
        self.assertEqual(Exam.objects.filter(status="published").count(), 2)
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("seed_demo", stdout=out)

    @override_settings(DEBUG=False)
    def test_demo_disabled_in_production(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("seed_demo", stdout=StringIO())
