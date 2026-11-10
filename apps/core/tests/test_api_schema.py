"""The OpenAPI schema behind /api/docs/ and /api/redoc/."""

from django.test import SimpleTestCase
from drf_spectacular.generators import SchemaGenerator

from apps.core.api.schema import SUMMARIES

METHODS = ("get", "post", "put", "patch", "delete")


class SchemaTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.operations = {
            op["operationId"]: op
            for ops in SchemaGenerator().get_schema(public=True)["paths"].values()
            for method, op in ops.items()
            if method in METHODS
        }

    def test_every_operation_has_a_short_summary(self):
        """ReDoc's menu shows the summary; without one it shows the operation id."""
        for operation_id, op in self.operations.items():
            with self.subTest(operation_id):
                self.assertTrue(op.get("summary"))
                self.assertLessEqual(len(op["summary"]), 50)

    def test_standard_actions_are_named_from_the_resource(self):
        self.assertEqual(self.operations["fee_plans_list"]["summary"], "List fee plans")
        self.assertEqual(self.operations["people_retrieve"]["summary"], "Get a person")
        self.assertEqual(self.operations["exams_create"]["summary"], "Create an exam")
        self.assertEqual(
            self.operations["exams_publish_create"]["summary"], "Publish an exam's results"
        )

    def test_no_summary_is_written_for_an_operation_that_no_longer_exists(self):
        self.assertEqual(set(SUMMARIES) - set(self.operations), set())

    def test_menu_groups_have_readable_names(self):
        tags = {
            tag["name"]: tag["x-displayName"]
            for tag in SchemaGenerator().get_schema(public=True)["tags"]
        }
        self.assertEqual(tags["fee-plans"], "Fee plans")
        self.assertEqual(tags["auth"], "Signing in")
