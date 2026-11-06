"""The API error handler, called directly with the exceptions services can raise."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.test import SimpleTestCase

from apps.core.api.exceptions import exception_handler
from apps.core.exceptions import Conflict


class ExceptionHandlerTests(SimpleTestCase):
    def handle(self, exc):
        return exception_handler(exc, {"view": None, "request": None})

    def test_service_exceptions_become_api_responses(self):
        cases = [
            (Conflict("Reload before saving."), 409, "conflict"),
            (IntegrityError("duplicate key"), 409, "conflict"),  # a race past validation
            (ValidationError("Bad date."), 400, "invalid"),
            (PermissionDenied(), 403, "permission_denied"),
        ]
        for exc, status, code in cases:
            with self.subTest(exc=type(exc).__name__):
                response = self.handle(exc)
                self.assertEqual((response.status_code, response.data["code"]), (status, code))

    def test_field_errors_keep_their_field(self):
        response = self.handle(ValidationError({"date": "Not in the year."}))
        self.assertEqual(response.data["fields"], {"date": ["Not in the year."]})
        self.assertEqual(response.data["detail"], "Not in the year.")

    def test_unexpected_errors_are_left_to_django(self):
        """A bug (say a KeyError) must stay a 500 with a logged traceback, not a tidy 400."""
        self.assertIsNone(self.handle(KeyError("oops")))
