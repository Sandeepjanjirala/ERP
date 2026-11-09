"""CSV import: a full check first; then every row together, or none."""

import csv
import io

from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.core.testing import ApiTestCase
from apps.students.imports import COLUMNS, MAX_ROWS, read_csv
from apps.students.models import ImportBatch, Student
from apps.students.services import check_import, confirm_import
from apps.students.tasks import send_import_invites


def row(n, **changes):
    values = {
        "admission_number": f"NEW-{n}",
        "first_name": f"Pupil{n}",
        "last_name": "Rao",
        "email": f"pupil{n}@example.com",
        "classroom": "9-A",
        "joined_on": "",
        "phone": "",
        "guardian_first_name": "Lata",
        "guardian_last_name": "Rao",
        "guardian_email": "lata.rao@example.com",  # one mother for every row: siblings
        "guardian_phone": "",
        "relationship": "mother",
    }
    return {**values, **changes}


def csv_file(rows, columns=COLUMNS, encoding="utf-8", name="students.csv"):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return SimpleUploadedFile(name, out.getvalue().encode(encoding), content_type="text/csv")


class ReadCsvTests(ApiTestCase):
    def test_file_level_rules(self):
        too_many = [row(n) for n in range(MAX_ROWS + 1)]
        cases = {
            "not UTF-8": (csv_file([row(1, first_name="Zoë")], encoding="cp1252"), "UTF-8 text"),
            "missing column": (csv_file([row(1)], columns=COLUMNS[1:]), "Missing columns: admission_number"),
            "unknown column": (csv_file([row(1)], columns=[*COLUMNS, "gaurdian"]), "Unknown columns: gaurdian"),
            "no rows": (csv_file([]), "no rows"),
            "too many rows": (csv_file(too_many), "at most 500"),
        }  # fmt: skip
        for case, (upload, message) in cases.items():
            with self.subTest(case=case), self.assertRaisesMessage(ValidationError, message):
                read_csv(upload)
        big = SimpleUploadedFile("big.csv", b"x" * (2 * 1024 * 1024 + 1))
        with self.assertRaisesMessage(ValidationError, "larger than 2 MB"):
            read_csv(big)

    def test_excel_utf8_with_a_byte_order_mark_is_fine(self):
        upload = csv_file([row(1, first_name="Zoë")])
        upload = SimpleUploadedFile("s.csv", b"\xef\xbb\xbf" + upload.read())
        self.assertEqual(read_csv(upload)[0]["first_name"], "Zoë")


class ImportTests(ApiTestCase):
    def rows(self, *rows):
        joined = self.year.starts_on.isoformat()
        return [{**r, "joined_on": r["joined_on"] or joined} for r in rows]

    def check(self, rows, actor=None):
        return check_import(
            actor or self.admin, self.a, self.year, "students.csv", self.rows(*rows)
        )

    def test_the_check_is_a_dry_run(self):
        before = (User.objects.count(), Student.objects.count())
        batch = self.check([row(1), row(2)])
        self.assertEqual((batch.errors, batch.ready), ({}, True))
        self.assertEqual((User.objects.count(), Student.objects.count()), before)  # nothing kept
        self.assertFalse(AuditEvent.objects.filter(action="account.created").exists())
        self.assertTrue(AuditEvent.objects.filter(action="students.import.checked").exists())

    def test_every_problem_is_listed_against_its_row(self):
        batch = self.check(
            [
                row(1),
                row(2, classroom="9-Z"),
                row(3, joined_on="01/06/2026"),
                row(4, admission_number="NEW-1", email="other@example.com"),  # duplicate in file
                row(5, email=self.teacher.email),  # taken by an existing account
                row(6, guardian_email=self.teacher.email),  # not a parent
                row(7, relationship="aunt"),
                row(
                    8,
                    guardian_email="",
                    guardian_first_name="",
                    guardian_last_name="",
                    relationship="",
                ),  # no guardian: fine
            ]
        )
        problems = {number: " ".join(messages) for number, messages in batch.errors.items()}
        self.assertEqual(sorted(problems, key=int), ["3", "4", "5", "6", "7", "8"])
        self.assertIn("No class “9-Z”", problems["3"])
        self.assertIn("YYYY-MM-DD", problems["4"])
        self.assertIn("already exists", problems["5"])
        self.assertIn("email", problems["6"])
        self.assertIn("isn't a parent", problems["7"])
        self.assertIn("mother, father or guardian", problems["8"])
        self.assertFalse(batch.ready)
        with self.assertRaisesMessage(ValidationError, "Fix the problems"):
            confirm_import(self.admin, batch)

    def test_confirming_imports_every_row_and_invites_new_accounts(self):
        batch = self.check(
            [
                row(1),
                row(2),
                row(
                    3,
                    guardian_email="",
                    guardian_first_name="",
                    guardian_last_name="",
                    relationship="",
                ),
            ]
        )
        with self.captureOnCommitCallbacks(execute=True):
            batch = confirm_import(self.admin, batch)
        self.assertEqual(batch.status, ImportBatch.Status.IMPORTED)
        pupils = Student.objects.filter(admission_number__startswith="NEW-")
        self.assertEqual(pupils.count(), 3)
        self.assertTrue(all(p.enrollments.get().classroom == self.c for p in pupils))
        mother = User.objects.get(email="lata.rao@example.com")
        self.assertEqual(
            mother.guardian_profile.child_links.count(), 2
        )  # created once, linked twice
        self.assertTrue(User.objects.get(username="new-1").must_change_password)
        self.assertEqual(
            sorted(batch.accounts), ["lata.rao@example.com", "new-1", "new-2", "new-3"]
        )
        self.assertEqual(len(mail.outbox), 4)
        self.assertIn("/accounts/password/reset/", mail.outbox[0].body)
        event = AuditEvent.objects.get(action="students.imported")
        self.assertEqual(event.details, {"students": 3, "accounts_created": 4})
        # A second confirm (a double click) and a retried email job change nothing.
        self.assertEqual(confirm_import(self.admin, batch).status, ImportBatch.Status.IMPORTED)
        self.assertEqual(send_import_invites(batch.pk), 0)
        self.assertEqual((pupils.count(), len(mail.outbox)), (3, 4))

    def test_all_or_nothing_when_something_changed_since_the_check(self):
        batch = self.check([row(1), row(2)])
        User.objects.create_user("taken", "pupil2@example.com", "x", role="teacher", branch=self.a)
        batch = confirm_import(self.admin, batch)
        self.assertEqual(batch.status, ImportBatch.Status.CHECKED)
        self.assertIn("3", batch.errors)  # row 3 (pupil 2) now clashes
        self.assertFalse(Student.objects.filter(admission_number__startswith="NEW-").exists())
        self.assertFalse(User.objects.filter(email="lata.rao@example.com").exists())

    def test_only_managers_of_the_branch(self):
        for actor in (self.teacher, self.principal, self.accountant):
            with self.subTest(actor=actor.username), self.assertRaises(PermissionDenied):
                self.check([row(1)], actor=actor)
        with self.assertRaises(PermissionDenied):
            check_import(self.admin, self.b, self.year, "x.csv", self.rows(row(1)))
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse("student_import")).status_code, 403)


class ImportPageTests(ApiTestCase):
    def test_upload_preview_and_confirm(self):
        self.client.force_login(self.admin)
        joined = self.year.starts_on.isoformat()
        upload = csv_file([row(1, joined_on=joined), row(2, joined_on=joined)])
        form = {"branch": self.a.pk, "year": self.year.pk, "file": upload}
        response = self.client.post(reverse("student_import"), form, format="multipart")
        batch = ImportBatch.objects.get()
        self.assertRedirects(response, reverse("student_import_preview", args=[batch.pk]))
        preview = self.client.get(response.url)
        self.assertContains(preview, "Every row passed the check.")
        confirm = self.client.post(reverse("student_import_confirm", args=[batch.pk]), follow=True)
        self.assertContains(confirm, "2 students imported.")
        bad = csv_file([row(1)], columns=COLUMNS[1:])
        page = self.client.post(
            reverse("student_import"),
            {"branch": self.a.pk, "year": self.year.pk, "file": bad},
            format="multipart",
        )
        self.assertContains(page, "Missing columns: admission_number")
        template = self.client.get(reverse("student_import_template"))
        self.assertTrue(template.content.decode().startswith(",".join(COLUMNS)))

    def test_api_upload_and_confirm(self):
        self.as_user(self.admin)
        joined = self.year.starts_on.isoformat()
        upload = csv_file([row(1, joined_on=joined)])
        body = {"branch": self.a.pk, "year": self.year.pk, "file": upload}
        checked = self.client.post("/api/v1/student-imports/", body, format="multipart")
        self.assertEqual(checked.status_code, 201, checked.content)
        self.assertEqual((checked.json()["ready"], checked.json()["errors"]), (True, {}))
        done = self.client.post(f"/api/v1/student-imports/{checked.json()['id']}/confirm/")
        self.assertEqual(done.json()["status"], "imported")
        self.as_user(self.teacher)
        self.assertEqual(self.client.get("/api/v1/student-imports/").status_code, 403)
