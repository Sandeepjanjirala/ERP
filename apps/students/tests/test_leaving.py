"""Students who leave: records are kept, sign-in ends (sessions and API tokens too), and parents
get a limited grace period to download records and pay what is owed."""

import zipfile
from datetime import timedelta
from io import BytesIO

from django.conf import settings
from django.contrib.sessions.models import Session
from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.services import toggle_access
from apps.attendance.services import save_register
from apps.audit.models import AuditEvent
from apps.core.testing import PASSWORD
from apps.fees.services import cancel_invoice, record_counter_payment
from apps.fees.tests.base import FeesTestCase
from apps.students.models import Enrollment
from apps.students.services import record_leaving, review_access


@override_settings(LEAVER_GRACE_DAYS=30, LEAVER_FEES_GRACE_DAYS=90)
class LeavingTests(FeesTestCase):
    """Alice (whose mother is `parent`) leaves; Bob stays."""

    def leave(self, left_on=None, enrollment=None):
        return record_leaving(
            self.admin, enrollment or self.e1, left_on or self.today, "Moved to another city"
        )

    def review(self, days_later=1):
        with self.captureOnCommitCallbacks(execute=True):
            return review_access(self.today + timedelta(days=days_later))

    def refreshed(self, *users):
        for user in users:
            user.refresh_from_db()
        return users

    # Recording it -------------------------------------------------------------------------------

    def test_leaving_is_recorded_and_audited_and_nothing_is_deleted(self):
        self.leave()
        self.e1.refresh_from_db()
        self.assertEqual(self.e1.left_on, self.today)
        event = AuditEvent.objects.get(action="students.left")
        self.assertEqual(event.details["reason"], "Moved to another city")
        self.assertTrue(Enrollment.objects.filter(pk=self.e1.pk).exists())

    def test_leaving_needs_a_permitted_actor_a_reason_and_a_day_in_the_year(self):
        with self.assertRaises(PermissionDenied):
            record_leaving(self.teacher, self.e1, self.today, "Moved")
        with self.assertRaises(PermissionDenied):
            record_leaving(self.foreign_teacher, self.e1, self.today, "Moved")
        with self.assertRaisesMessage(ValidationError, "reason"):
            record_leaving(self.admin, self.e1, self.today, "  ")
        for day in (self.year.starts_on - timedelta(days=1), self.year.ends_on + timedelta(days=1)):
            with self.assertRaisesMessage(ValidationError, "Choose a day"):
                self.leave(day)

    def test_leaving_cannot_come_before_recorded_attendance(self):
        save_register(self.teacher, self.c, self.today, {self.e1.pk: "P", self.e2.pk: "P"}, 0)
        with self.assertRaisesMessage(ValidationError, "Attendance is recorded"):
            self.leave(self.today - timedelta(days=1))
        self.leave(self.today)

    def test_web_page_and_api_record_leaving(self):
        self.sign_in(self.admin)
        url = reverse("enrollment_leave", args=[self.e1.pk])
        self.assertContains(self.client.get(url), "Last day at school")
        response = self.client.post(url, {"left_on": self.today.isoformat(), "reason": "Moved"})
        self.assertRedirects(response, reverse("student_report", args=[self.e1.student_id]))
        self.e1.refresh_from_db()
        self.assertEqual(self.e1.left_on, self.today)

        api = APIClient()
        api.force_authenticate(self.admin)
        response = api.post(
            f"/api/v1/enrollments/{self.e2.pk}/leave/",
            {"left_on": self.today.isoformat(), "reason": "Moved"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["left_on"], self.today.isoformat())
        api.force_authenticate(self.teacher)
        response = api.post(
            f"/api/v1/enrollments/{self.e2.pk}/leave/", {"left_on": "", "reason": ""}, format="json"
        )
        self.assertEqual(response.status_code, 403)

    def test_only_managers_see_the_leaving_page(self):
        self.sign_in(self.teacher)
        response = self.client.get(reverse("enrollment_leave", args=[self.e1.pk]))
        self.assertEqual(response.status_code, 403)

    # Students -----------------------------------------------------------------------------------

    def test_a_student_is_switched_off_the_day_after_leaving_and_on_when_enrolled_again(self):
        self.leave()
        self.assertEqual(review_access(self.today)["students_off"], 0)  # still their last day
        counts = self.review(days_later=1)
        self.assertEqual(counts["students_off"], 1)
        alice, bob = self.refreshed(self.e1.student.user, self.e2.student.user)
        self.assertFalse(alice.is_active)
        self.assertEqual(alice.deactivated_reason, "left_school")
        self.assertTrue(bob.is_active)
        self.assertTrue(
            AuditEvent.objects.filter(action="account.deactivated_automatically").exists()
        )

        self.e1.left_on = None
        self.e1.save(update_fields=["left_on"])
        self.assertEqual(self.review(days_later=2)["students_on"], 1)
        (alice,) = self.refreshed(alice)
        self.assertTrue(alice.is_active)
        self.assertEqual(alice.deactivated_reason, "")

    def test_the_review_never_switches_on_an_account_an_administrator_switched_off(self):
        toggle_access(self.admin, self.e2.student.user)
        self.review()
        self.e2.student.user.refresh_from_db()
        self.assertFalse(self.e2.student.user.is_active)

    def test_running_the_review_twice_changes_nothing_more(self):
        self.leave()
        self.review()
        events = AuditEvent.objects.count()
        self.assertEqual(set(self.review().values()), {0})
        self.assertEqual(AuditEvent.objects.count(), events)

    # Revocation ---------------------------------------------------------------------------------

    def test_switching_off_ends_web_sessions_and_api_tokens(self):
        alice = self.e1.student.user
        browser = self.client_class()
        browser.login(username=alice.username, password=PASSWORD)
        other_session = self.client_class()
        other_session.login(username=self.e2.student.user.username, password=PASSWORD)
        api = APIClient()
        tokens = api.post(
            "/api/v1/auth/token/", {"username": alice.username, "password": PASSWORD}
        ).json()

        self.leave()
        self.review()

        alices = [
            s
            for s in Session.objects.all()
            if s.get_decoded().get("_auth_user_id") == str(alice.pk)
        ]
        self.assertEqual(alices, [])
        self.assertEqual(Session.objects.count(), 1)  # Bob is still signed in
        refreshed = api.post("/api/v1/auth/token/refresh/", {"refresh": tokens["refresh"]})
        self.assertEqual(refreshed.status_code, 401)

        # Switched back on, the old refresh token still doesn't work: a new sign-in is needed.
        self.e1.left_on = None
        self.e1.save(update_fields=["left_on"])
        self.review(days_later=2)
        refreshed = api.post("/api/v1/auth/token/refresh/", {"refresh": tokens["refresh"]})
        self.assertEqual(refreshed.status_code, 401)
        signed_in = api.post(
            "/api/v1/auth/token/", {"username": alice.username, "password": PASSWORD}
        )
        self.assertEqual(signed_in.status_code, 200)

    def test_an_administrator_switching_off_also_revokes(self):
        api = APIClient()
        tokens = api.post(
            "/api/v1/auth/token/", {"username": self.teacher.username, "password": PASSWORD}
        ).json()
        self.client.login(username=self.teacher.username, password=PASSWORD)
        toggle_access(self.admin, self.teacher)
        self.assertEqual(Session.objects.count(), 0)
        refreshed = api.post("/api/v1/auth/token/refresh/", {"refresh": tokens["refresh"]})
        self.assertEqual(refreshed.status_code, 401)

    # Parents ------------------------------------------------------------------------------------

    def test_a_parent_gets_the_grace_period_with_one_email_then_is_switched_off(self):
        self.leave()
        counts = self.review(days_later=1)
        self.assertEqual(counts["parents_told"], 1)
        (parent,) = self.refreshed(self.parent)
        self.assertTrue(parent.is_active)
        self.assertEqual(parent.access_ends_on, self.today + timedelta(days=30))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.parent.email])
        ends_on = parent.access_ends_on
        self.assertIn(f"{ends_on.day} {ends_on:%B %Y}", mail.outbox[0].body)
        self.assertNotIn("unpaid", mail.outbox[0].body)

        self.review(days_later=2)
        self.review(days_later=30)
        self.assertEqual(len(mail.outbox), 1)  # told once
        self.assertTrue(self.refreshed(self.parent)[0].is_active)  # still on, last day

        self.assertEqual(self.review(days_later=31)["parents_off"], 1)
        (parent,) = self.refreshed(self.parent)
        self.assertFalse(parent.is_active)
        self.assertEqual(parent.deactivated_reason, "children_left")

    def test_the_banner_shows_the_end_date_to_the_parent(self):
        self.leave()
        self.review()
        self.parent.refresh_from_db()
        self.sign_in(self.parent)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Your account stops working after")
        self.assertContains(response, reverse("student_records", args=[self.e1.student_id]))

    def test_a_parent_keeps_access_while_another_child_is_enrolled(self):
        self.e2.student.guardian_links.create(
            guardian=self.parent.guardian_profile, relationship="mother"
        )
        self.leave()
        self.review()
        (parent,) = self.refreshed(self.parent)
        self.assertTrue(parent.is_active)
        self.assertIsNone(parent.access_ends_on)
        self.assertEqual(len(mail.outbox), 0)

    def test_fees_owed_extend_access_but_not_indefinitely(self):
        self.alices()
        self.leave()
        self.review()
        (parent,) = self.refreshed(self.parent)
        self.assertEqual(parent.access_ends_on, self.today + timedelta(days=90))
        self.assertIn("unpaid", mail.outbox[0].body)
        self.assertIn(reverse("fees"), mail.outbox[0].body)
        self.assertTrue(self.refreshed(self.parent)[0].is_active)
        self.review(days_later=90)
        self.assertTrue(self.refreshed(self.parent)[0].is_active)
        self.review(days_later=91)
        self.assertFalse(self.refreshed(self.parent)[0].is_active)

    def test_an_announced_end_date_is_never_brought_forward(self):
        invoice = self.alices()
        self.leave()
        self.review()
        record_counter_payment(self.accountant, invoice, invoice.total_paise, "cash")
        self.review(days_later=2)
        (parent,) = self.refreshed(self.parent)
        self.assertEqual(parent.access_ends_on, self.today + timedelta(days=90))
        self.assertEqual(len(mail.outbox), 1)

    def test_an_invoice_issued_after_access_ended_reopens_it_within_the_limit(self):
        self.leave()
        self.review()
        self.review(days_later=31)
        self.assertFalse(self.refreshed(self.parent)[0].is_active)
        invoice = self.alices()
        counts = self.review(days_later=32)
        self.assertEqual(counts["parents_on"], 1)
        (parent,) = self.refreshed(self.parent)
        self.assertTrue(parent.is_active)
        self.assertEqual(parent.access_ends_on, self.today + timedelta(days=90))
        cancel_invoice(self.admin, invoice, "Issued by mistake")

    def test_an_administrator_switching_a_leaver_back_on_grants_a_fresh_grace_period(self):
        self.leave()
        self.review()
        self.review(days_later=31)
        self.assertFalse(self.refreshed(self.parent)[0].is_active)
        toggle_access(self.admin, self.parent)
        (parent,) = self.refreshed(self.parent)
        self.assertTrue(parent.is_active)
        # Granted from today (the real date), so later reviews leave it on until then.
        self.assertGreater(parent.access_ends_on, self.today)

    def test_a_parent_whose_children_were_never_enrolled_is_left_alone(self):
        Enrollment.objects.filter(student=self.e1.student).delete()
        self.review()
        (parent,) = self.refreshed(self.parent)
        self.assertTrue(parent.is_active)
        self.assertIsNone(parent.access_ends_on)

    def test_the_daily_job_is_scheduled(self):
        tasks = {entry["task"] for entry in settings.CELERY_BEAT_SCHEDULE.values()}
        self.assertIn("apps.students.tasks.review_account_access", tasks)

    # Records ------------------------------------------------------------------------------------

    def names_in(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        return sorted(zipfile.ZipFile(BytesIO(response.content)).namelist())

    def test_a_parent_downloads_report_cards_statement_and_receipts(self):
        invoice = self.alices()
        record_counter_payment(self.accountant, invoice, 100000, "cash")
        self.leave()
        self.sign_in(self.parent)
        names = self.names_in(
            self.client.get(reverse("student_records", args=[self.e1.student_id]))
        )
        self.assertEqual(len([n for n in names if n.startswith("report-cards/")]), 1)
        self.assertIn(f"fee-statement-{self.e1.student.admission_number}.pdf", names)
        self.assertEqual(len([n for n in names if n.startswith("receipts/")]), 1)
        self.assertTrue(AuditEvent.objects.filter(action="report.records_downloaded").exists())

    def test_a_student_gets_report_cards_but_no_fee_records(self):
        self.alices()
        self.sign_in(self.e1.student.user)
        names = self.names_in(
            self.client.get(reverse("student_records", args=[self.e1.student_id]))
        )
        self.assertTrue(names)
        self.assertTrue(all(n.startswith("report-cards/") for n in names))

    def test_nobody_downloads_another_family_s_records(self):
        self.sign_in(self.parent)
        response = self.client.get(reverse("student_records", args=[self.e2.student_id]))
        self.assertEqual(response.status_code, 404)
        self.sign_in(self.accountant)
        response = self.client.get(reverse("student_records", args=[self.e1.student_id]))
        self.assertEqual(response.status_code, 403)

    def test_staff_download_records_for_a_family_after_access_ends(self):
        self.leave()
        self.review(days_later=31)
        self.sign_in(self.admin)
        names = self.names_in(
            self.client.get(reverse("student_records", args=[self.e1.student_id]))
        )
        self.assertTrue(names)


class SwitchedOffUsersTests(FeesTestCase):
    def test_a_switched_off_parent_cannot_sign_in(self):
        self.parent.is_active = False
        self.parent.save(update_fields=["is_active"])
        self.assertFalse(self.client.login(username=self.parent.username, password=PASSWORD))
        self.assertFalse(User.objects.get(pk=self.parent.pk).is_active)
