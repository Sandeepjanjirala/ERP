"""Terms: each exam is in the term its date falls in; dates outside every term are refused."""

from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from apps.academics.models import AcademicYear, Term
from apps.academics.services import save_setup_record, save_terms
from apps.audit.models import AuditEvent
from apps.core.testing import ApiTestCase
from apps.exams.models import Exam


class TermTests(ApiTestCase):
    def terms(self):
        return list(Term.objects.filter(year=self.year))

    def new_exam(self, day, **fields):
        return Exam.objects.create(
            classroom=self.c,
            subject=self.math,
            title=fields.pop("title", "Quiz"),
            date=day,
            max_marks=10,
            pass_marks=4,
            **fields,
        )

    def test_exams_go_into_the_term_of_their_date(self):
        first, second = self.terms()
        early = self.new_exam(first.starts_on)
        late = self.new_exam(second.ends_on, title="Final")
        self.assertEqual((early.term, late.term), (first, second))
        early.date = second.starts_on
        early.save()
        self.assertEqual(early.term, second)  # a new date moves the exam

    def test_a_date_outside_every_term_is_refused_clearly(self):
        first, second = self.terms()
        Term.objects.filter(pk=second.pk).update(starts_on=second.starts_on + timedelta(days=10))
        gap = second.starts_on + timedelta(days=2)
        with self.assertRaisesMessage(ValidationError, "No term of Test year covers"):
            self.new_exam(gap)
        self.as_user(self.teacher)
        response = self.client.post(
            "/api/v1/exams/",
            {
                "classroom": self.c.pk,
                "subject": self.math.pk,
                "title": "Gap quiz",
                "date": gap.isoformat(),
                "max_marks": "10",
                "pass_marks": "4",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("No term of Test year covers", response.json()["fields"]["date"][0])

    def rows(self, *spans):
        return [
            {"name": f"Term {n}", "starts_on": starts, "ends_on": ends}
            for n, (starts, ends) in enumerate(spans, start=1)
        ]

    def test_a_set_of_terms_must_fit_the_year_without_overlaps(self):
        first, second = self.terms()
        year = self.year
        cases = {
            "overlap": (self.rows((year.starts_on, second.starts_on), (second.starts_on, year.ends_on)), "Term 1 and Term 2 overlap"),
            "outside the year": (self.rows((year.starts_on - timedelta(days=1), year.ends_on)), "must fall within Test year"),
            "backwards": (self.rows((year.ends_on, year.starts_on)), "ends before it starts"),
            "same names": ([{**row, "name": "Term"} for row in self.rows((year.starts_on, first.ends_on), (second.starts_on, year.ends_on))], "its own name"),
            "none": ([], "at least one term"),
        }  # fmt: skip
        for case, (rows, message) in cases.items():
            with self.subTest(case=case), self.assertRaisesMessage(ValidationError, message):
                save_terms(self.root, year, rows)
        self.assertEqual(self.terms(), [first, second])  # nothing changed

    def test_moving_the_boundary_moves_the_exam_on_it(self):
        first, second = self.terms()
        exam = self.new_exam(first.ends_on)  # the last day of Term 1
        self.assertEqual(exam.term, first)
        boundary = first.ends_on - timedelta(days=1)
        save_terms(
            self.root,
            self.year,
            [
                {"id": first.pk, "name": "Term 1", "starts_on": first.starts_on, "ends_on": boundary},
                {"id": second.pk, "name": "Term 2", "starts_on": boundary + timedelta(days=1), "ends_on": second.ends_on},
            ],
        )  # fmt: skip
        exam.refresh_from_db()
        self.assertEqual(exam.term, second)  # both terms changed together: no gap, no overlap
        event = AuditEvent.objects.get(action="setup.terms.saved")
        self.assertGreaterEqual(event.details["exams_moved"], 1)

    def test_a_set_that_leaves_an_exam_outside_is_refused(self):
        first, second = self.terms()
        exam = self.new_exam(second.starts_on)
        later = second.starts_on + timedelta(days=5)
        with self.assertRaisesMessage(ValidationError, "would be outside every term"):
            save_terms(
                self.root,
                self.year,
                [
                    {"id": first.pk, "name": "Term 1", "starts_on": first.starts_on, "ends_on": first.ends_on},
                    {"id": second.pk, "name": "Term 2", "starts_on": later, "ends_on": second.ends_on},
                ],
            )  # fmt: skip
        self.assertEqual(self.terms(), [first, second])
        second.refresh_from_db()
        exam.refresh_from_db()
        self.assertEqual((second.starts_on, exam.term), (later - timedelta(days=5), second))

    def test_merging_terms_moves_their_exams_and_names_can_swap(self):
        first, second = self.terms()
        exam = self.new_exam(second.ends_on)
        whole = [{"id": first.pk, "name": "Whole year", "starts_on": self.year.starts_on, "ends_on": self.year.ends_on}]  # fmt: skip
        save_terms(self.root, self.year, whole)
        exam.refresh_from_db()
        self.assertEqual((self.terms(), exam.term), ([first], first))
        self.assertFalse(Term.objects.filter(pk=second.pk).exists())
        # Two terms, then their names swapped: no clash on the way.
        a, b = self.terms()[0], None
        save_terms(
            self.root,
            self.year,
            self.rows((self.year.starts_on, first.ends_on), (second.starts_on, self.year.ends_on)),
        )
        a, b = self.terms()
        save_terms(
            self.root,
            self.year,
            [
                {"id": a.pk, "name": "Term 2", "starts_on": a.starts_on, "ends_on": a.ends_on},
                {"id": b.pk, "name": "Term 1", "starts_on": b.starts_on, "ends_on": b.ends_on},
            ],
        )  # fmt: skip
        self.assertEqual([t.name for t in self.terms()], ["Term 2", "Term 1"])

    def test_the_terms_page(self):
        first, second = self.terms()
        self.client.force_login(self.root)
        url = reverse("year_terms", args=[self.year.pk])
        form = {
            "form-TOTAL_FORMS": "3",
            "form-INITIAL_FORMS": "2",
            "form-0-id": first.pk, "form-0-name": "Autumn",
            "form-0-starts_on": first.starts_on, "form-0-ends_on": first.ends_on,
            "form-1-id": second.pk, "form-1-name": "Spring",
            "form-1-starts_on": second.starts_on, "form-1-ends_on": second.ends_on,
            "form-2-name": "", "form-2-starts_on": "", "form-2-ends_on": "",
        }  # fmt: skip
        self.assertRedirects(self.client.post(url, form, format="multipart"), reverse("setup"))
        self.assertEqual([t.name for t in self.terms()], ["Autumn", "Spring"])
        page = self.client.post(
            url, {**form, "form-1-starts_on": first.ends_on}, format="multipart"
        )
        self.assertContains(page, "Autumn and Spring overlap.")
        page = self.client.post(url, {**form, "form-2-name": "Summer"}, format="multipart")
        self.assertContains(page, "Give the term a name, a start date and an end date.")

    def test_a_new_year_gets_two_terms_covering_it(self):
        year = AcademicYear(
            name="Next year",
            starts_on=self.year.ends_on + timedelta(days=1),
            ends_on=self.year.ends_on + timedelta(days=365),
        )
        save_setup_record(self.root, "year", year)
        terms = list(year.terms.all())
        self.assertEqual([t.name for t in terms], ["Term 1", "Term 2"])
        self.assertEqual((terms[0].starts_on, terms[1].ends_on), (year.starts_on, year.ends_on))
        self.assertEqual(terms[0].ends_on + timedelta(days=1), terms[1].starts_on)

    def test_only_super_admins_manage_terms(self):
        first, second = self.terms()
        rows = self.rows((first.starts_on, first.ends_on), (second.starts_on, second.ends_on))
        with self.assertRaises(PermissionDenied):
            save_terms(self.admin, self.year, rows)
        self.client.force_login(self.admin)
        url = reverse("year_terms", args=[self.year.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        api = f"/api/v1/years/{self.year.pk}/terms/"
        body = {"terms": [{**row, "starts_on": str(row["starts_on"]), "ends_on": str(row["ends_on"])} for row in rows]}  # fmt: skip
        self.as_user(self.admin)
        self.assertEqual(self.client.put(api, body, format="json").status_code, 403)
        self.assertEqual(len(self.client.get(api).json()["terms"]), 2)  # anyone may read them
        self.as_user(self.root)
        response = self.client.put(api, body, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual([t["name"] for t in response.json()["terms"]], ["Term 1", "Term 2"])

    def test_exams_in_the_api_show_their_term(self):
        self.as_user(self.teacher)
        rows = self.client.get("/api/v1/exams/").json()["results"]
        self.assertTrue(rows and all(row["term"]["name"].startswith("Term ") for row in rows))
        term = self.terms()[0]
        filtered = self.client.get(f"/api/v1/exams/?term={term.pk}").json()["results"]
        self.assertTrue(all(row["term"]["id"] == term.pk for row in filtered))
