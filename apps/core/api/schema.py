"""The OpenAPI schema: every operation gets a short summary, so ReDoc's menu reads "List fee
plans" or "Publish an exam" rather than an operation id such as `fee_plans_list`.

Standard viewset actions are named from the resource; every other operation is in SUMMARIES.
apps/core/tests/test_api_schema.py fails if an operation has neither.
"""

from drf_spectacular.openapi import AutoSchema

VERBS = {
    "list": "List",
    "retrieve": "Get",
    "create": "Create",
    "update": "Replace",
    "partial_update": "Update",
    "destroy": "Delete",
}
# Resources whose singular isn't the plural without its "s".
SINGULAR = {"activity": "activity event", "branches": "branch", "people": "person"}
PLURAL = {"activity": "the activity log"}

# By operation id: actions and views that aren't a plain list, get, create or update.
SUMMARIES = {
    "auth_token_create": "Sign in (get a token pair)",
    "auth_token_refresh_create": "Refresh the access token",
    "auth_logout_create": "Sign out (revoke the refresh token)",
    "me_retrieve": "Get the signed-in user",
    "me_password_create": "Change your password",
    "organization_retrieve": "Get the school group",
    "organization_partial_update": "Rename the school group",
    "people_toggle_access_create": "Switch an account off or on",
    "years_terms_retrieve": "Get a year's terms",
    "years_terms_update": "Replace a year's terms",
    "classrooms_timetable_retrieve": "Get a class's timetable",
    "classrooms_timetable_create": "Set one timetable cell",
    "timetable_mine_list": "Get my weekly lessons",
    "classrooms_register_retrieve": "Get a class's register for a day",
    "classrooms_register_update": "Save a class's register for a day",
    "classrooms_promotion_list": "Preview a class's promotion",
    "classrooms_promotion_create": "Promote a class",
    "students_guardians_list": "List a student's parents",
    "students_guardians_create": "Add a parent account for a student",
    "students_guardians_link_create": "Link an existing parent to a student",
    "students_guardians_make_primary_create": "Make a parent the primary contact",
    "students_create": "Admit a student",
    "student_imports_create": "Check a CSV import (dry run)",
    "student_imports_confirm_create": "Confirm a checked import",
    "students_report_retrieve": "Get a student's report",
    "students_report_card_retrieve": "Download a report card (PDF)",
    "exams_marks_retrieve": "Get an exam's mark sheet",
    "exams_marks_update": "Save an exam's marks",
    "exams_submit_create": "Submit an exam's marks",
    "exams_publish_create": "Publish an exam's results",
    "exams_reopen_create": "Reopen a submitted or published exam",
    "grading_scales_create": "Save a new grading scale version",
    "leave_requests_create": "Apply for leave",
    "leave_requests_approve_create": "Approve a leave request",
    "leave_requests_reject_create": "Refuse a leave request",
    "notifications_read_create": "Mark a notification read",
    "notifications_read_all_create": "Mark all notifications read",
    "notifications_unread_count_retrieve": "Count unread notifications",
    "dashboard_retrieve": "Get the dashboard",
    "reports_performance_retrieve": "Get results performance",
    "reports_performance_export_retrieve": "Download published results (CSV)",
    "fee_plans_issue_create": "Issue invoices from a fee plan",
    "invoices_payment_create": "Record a counter payment",
    "invoices_concession_create": "Grant a concession",
    "invoices_cancel_create": "Cancel an invoice",
    "invoices_pay_online_create": "Start an online payment",
    "receipts_pdf_retrieve": "Download a receipt (PDF)",
    "payments_webhook_create": "Payment provider webhook",
}


def resource(path, plural):
    """'/api/v1/fee-plans/{id}/' -> 'fee plans' (or 'fee plan')."""
    words = path.removeprefix("/api/v1/").split("/")[0].replace("-", " ")
    if plural:
        return PLURAL.get(words, words)
    return SINGULAR.get(words, words.removesuffix("s"))


def article(noun):
    return f"an {noun}" if noun[0] in "aeiou" else f"a {noun}"


class EduNexaAutoSchema(AutoSchema):
    def get_summary(self):
        """An explicit extend_schema(summary=...) wins, then SUMMARIES, then a standard
        action named from the resource."""
        summary = super().get_summary()
        if summary:
            return summary
        operation_id = self.get_operation_id()
        if operation_id in SUMMARIES:
            return SUMMARIES[operation_id]
        action = getattr(self.view, "action", None)
        if action in VERBS:
            many = action == "list"
            noun = resource(self.path, plural=many)
            return f"{VERBS[action]} {noun if many else article(noun)}"
        return None


# ReDoc's menu groups operations by tag (the first part of the path); x-displayName is the label.
TAG_NAMES = {"auth": "Signing in", "me": "Your account", "activity": "Activity log"}


def tag_display_names(result, generator, request, public):
    """A postprocessing hook: give every tag a readable menu label ("fee-plans" -> "Fee plans")."""
    used = sorted(
        {
            tag
            for operations in result["paths"].values()
            for operation in operations.values()
            if isinstance(operation, dict)
            for tag in operation.get("tags", [])
        }
    )
    result["tags"] = [
        {"name": tag, "x-displayName": TAG_NAMES.get(tag, tag.replace("-", " ").capitalize())}
        for tag in used
    ]
    return result
