"""One-tap attendance: a button per status, "Mark all present", and htmx saves in place."""

from django.urls import reverse

from apps.attendance.models import AttendanceSession
from apps.core.testing import SchoolTestCase


class OneTapRegisterTests(SchoolTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("attendance") + f"?classroom={self.c.pk}&date={self.today.isoformat()}"
        self.client.force_login(self.teacher)  # the class teacher of 9-A
        self.statuses = {f"status_{e.pk}": "P" for e in (self.e1, self.e2)}

    def test_a_button_per_status_and_mark_all_present(self):
        page = self.client.get(self.url)
        self.assertContains(page, f'type="radio" name="status_{self.e1.pk}" value="A"', html=False)
        filled = self.client.post(self.url, {"version": 0, "fill": "P"})
        self.assertContains(filled, "Everyone is marked present.")
        for enrollment in (self.e1, self.e2):
            self.assertEqual(filled.context["form"][f"status_{enrollment.pk}"].value(), "P")
        self.assertFalse(AttendanceSession.objects.exists())  # filling saves nothing

    def test_htmx_saves_and_replaces_only_the_register(self):
        response = self.client.post(
            self.url, {"version": 0, **self.statuses}, HTTP_HX_REQUEST="true"
        )
        self.assertTemplateUsed(response, "attendance/_register.html")
        self.assertTemplateNotUsed(response, "base.html")
        self.assertContains(response, "Daily attendance saved.")
        session = AttendanceSession.objects.get()
        self.assertEqual(response.context["form"]["version"].value(), session.version)
        # The same save again carries an old version: refused in place, nothing overwritten.
        stale = self.client.post(
            self.url,
            {"version": 0, **self.statuses, "reason": "again"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(stale.status_code, 200)  # htmx swaps in only 2xx responses
        self.assertContains(stale, "Another user changed this register")
        session.refresh_from_db()
        self.assertEqual(session.version, 1)

    def test_every_student_needs_a_status(self):
        partial = {f"status_{self.e1.pk}": "P"}
        response = self.client.post(self.url, {"version": 0, **partial}, HTTP_HX_REQUEST="true")
        self.assertContains(response, "Choose a status.")
        self.assertFalse(AttendanceSession.objects.exists())

    def test_only_the_class_teacher_or_admin_may_fill_or_save(self):
        self.client.force_login(self.other_teacher)
        for body in ({"version": 0, "fill": "P"}, {"version": 0, **self.statuses}):
            with self.subTest(body=sorted(body)):
                self.assertEqual(self.client.post(self.url, body).status_code, 403)
        page = self.client.get(self.url)
        self.assertNotContains(page, "Mark all present")
        self.assertContains(page, "disabled")
