"""?ordering= is allowed only on declared fields, and pages stay stable when values repeat."""

from rest_framework.filters import OrderingFilter
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.accounts.api.views import PeopleViewSet
from apps.accounts.models import User
from apps.accounts.tests.factories import UserFactory
from apps.core.api.filters import StableOrderingFilter
from apps.core.testing import ApiTestCase


class OrderingTests(ApiTestCase):
    def usernames(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.content)
        return [row["username"] for row in response.json()["results"]]

    def test_undeclared_and_computed_fields_are_ignored(self):
        """These used to reach the database as ORDER BY on a non-column: a 500."""
        self.as_user(self.admin)
        default = self.usernames("/api/v1/people/?page_size=100")
        for term in ("get_role_display", "can_edit", "display_name", "email", "password"):
            with self.subTest(term=term):
                self.assertEqual(
                    self.usernames(f"/api/v1/people/?page_size=100&ordering={term}"), default
                )

    def test_declared_fields_sort_both_ways(self):
        self.as_user(self.admin)
        ascending = self.usernames("/api/v1/people/?page_size=100&ordering=username")
        self.assertEqual(ascending, sorted(ascending))
        descending = self.usernames("/api/v1/people/?page_size=100&ordering=-username")
        self.assertEqual(descending, ascending[::-1])

    def test_a_view_that_declares_nothing_allows_no_sorting(self):
        """DRF's stock filter would offer every serializer source, including model methods.

        `get_role_display` (behind PersonSerializer.role_label) is a method, not a column, so
        sorting on it was a 500 before the people list declared its fields. A future view that
        forgets `ordering_fields` must fall back to no sorting, not to that list.
        """

        class Undeclared(PeopleViewSet):
            ordering_fields = None

        view, queryset = Undeclared(), User.objects.all()
        view.action = "list"
        request = Request(APIRequestFactory().get("/"))
        view.request = request
        stock = [name for name, _ in OrderingFilter().get_valid_fields(queryset, view)]
        self.assertIn("get_role_display", stock)  # the hazard this filter removes
        self.assertEqual(StableOrderingFilter().get_valid_fields(queryset, view), [])

    def test_a_requested_sort_always_ends_with_the_primary_key(self):
        """A database may return rows with equal values in any order; the pk makes it unique."""
        request = Request(APIRequestFactory().get("/", {"ordering": "-first_name,username"}))
        view = PeopleViewSet()
        ordering = StableOrderingFilter().get_ordering(request, User.objects.all(), view)
        self.assertEqual(ordering, ["-first_name", "username", "pk"])
        plain = Request(APIRequestFactory().get("/"))
        self.assertIsNone(StableOrderingFilter().get_ordering(plain, User.objects.all(), view))

    def test_repeated_values_still_page_without_gaps_or_repeats(self):
        """Twelve teachers called "Kiran": page by page, every one appears exactly once.

        A behaviour check only: databases often return ties in insertion order, so this could
        pass without the tiebreak. The guarantee is the pk test above.
        """
        for _ in range(12):
            UserFactory(first_name="Kiran", role=User.Role.TEACHER, branch=self.a)
        self.as_user(self.admin)
        # Walk every page: where the Kirans fall depends on the database's collation (PostgreSQL
        # sorts "accountant" before "Kiran"; SQLite sorts capitals first).
        seen, url = [], "/api/v1/people/?ordering=first_name&page_size=5"
        while url:
            body = self.client.get(url).json()
            seen += [row["username"] for row in body["results"]]
            url = body["next"]
        kirans = [name for name in seen if User.objects.get(username=name).first_name == "Kiran"]
        self.assertEqual(len(kirans), 12)
        self.assertEqual(len(seen), len(set(seen)))

    def test_lists_without_declared_fields_ignore_the_parameter(self):
        self.as_user(self.root)
        default = self.client.get("/api/v1/classrooms/").json()["results"]
        reordered = self.client.get("/api/v1/classrooms/?ordering=-id").json()["results"]
        self.assertEqual(default, reordered)
