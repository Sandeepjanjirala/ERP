"""The global search (Ctrl+K): students, people and invoices, each limited to the user's scope."""

from django.urls import reverse

from apps.fees.tests.base import FeesTestCase
from apps.reports.selectors import search_everything


class SearchTests(FeesTestCase):
    def setUp(self):
        self.invoices = self.issue()

    def found(self, user, text):
        return {
            group: None if rows is None else sorted(str(row.pk) for row in rows)
            for group, rows in search_everything(user, text).items()
        }

    def test_each_role_searches_only_what_it_may_see(self):
        alice = str(self.e1.student_id)
        self.assertEqual(self.found(self.admin, "alice")["students"], [alice])
        self.assertEqual(self.found(self.teacher, "alice")["students"], [alice])
        self.assertEqual(self.found(self.foreign_teacher, "alice")["students"], [])
        self.assertIsNone(self.found(self.accountant, "alice")["students"])  # nothing academic
        self.assertIsNone(self.found(self.teacher, "alice")["people"])
        self.assertIsNone(self.found(self.teacher, "alice")["invoices"])
        alices = str(self.invoices[self.e1.student_id].pk)
        self.assertEqual(self.found(self.accountant, "alice")["invoices"], [alices])
        self.assertEqual(self.found(self.parent, "alice")["invoices"], [alices])
        self.assertEqual(self.found(self.parent, "bob")["invoices"], [])  # not her child

    def test_people_by_name_username_or_email(self):
        self.assertEqual(
            self.found(self.principal, "otherteacher@")["people"], [str(self.other_teacher.pk)]
        )
        self.assertEqual(self.found(self.principal, "foreignteacher")["people"], [])  # other branch
        self.assertEqual(
            self.found(self.root, "foreignteacher")["people"], [str(self.foreign_teacher.pk)]
        )

    def test_invoices_by_number(self):
        invoice = self.invoices[self.e2.student_id]
        self.assertEqual(
            self.found(self.accountant, f"#{invoice.pk}")["invoices"], [str(invoice.pk)]
        )

    def test_short_queries_find_nothing(self):
        self.assertEqual(set(self.found(self.admin, "a").values()), {None})

    def test_the_page_and_its_live_results(self):
        self.sign_in(self.admin)
        page = self.client.get(reverse("search"), {"q": "ali"})
        self.assertContains(page, reverse("student_report", args=[self.e1.student_id]))
        self.assertContains(page, 'hx-select="#results"')
        alices = self.invoices[self.e1.student_id]
        self.assertContains(page, reverse("invoice_detail", args=[alices.pk]))  # by student name
        response = self.client.get(reverse("search"), {"q": "zzz"}, HTTP_HX_REQUEST="true")
        self.assertContains(response, "No students match.")

    def test_who_has_the_search_box(self):
        for user, has_box in (
            (self.admin, True),
            (self.teacher, True),
            (self.accountant, True),
            (self.parent, True),
            (self.e1.student.user, False),
        ):
            with self.subTest(user=user.username):
                self.sign_in(user)
                page = self.client.get(reverse("dashboard"))
                self.assertEqual('id="global-search"' in page.content.decode(), has_box)
        self.sign_in(self.e1.student.user)
        self.assertEqual(self.client.get(reverse("search")).status_code, 403)
