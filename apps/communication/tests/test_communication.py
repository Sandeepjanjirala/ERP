"""Announcements reach exactly their audience; notifications are delivered once; the bell works."""

from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from apps.accounts.models import User
from apps.communication.models import Announcement, Notification
from apps.communication.selectors import announcements
from apps.communication.services import notify, publish_announcement
from apps.communication.tasks import deliver_announcement
from apps.core.testing import PASSWORD, ApiTestCase, SchoolTestCase


def recipients(announcement):
    return set(
        Notification.objects.filter(key=f"announcement:{announcement.pk}").values_list(
            "recipient__username", flat=True
        )
    )


class AnnouncementDeliveryTests(SchoolTestCase):
    def publish(self, actor, **fields):
        fields.setdefault("branch", self.a)
        announcement = Announcement(title="Sports day", body="Friday at 9.", **fields)
        with self.captureOnCommitCallbacks(execute=True):
            publish_announcement(actor, announcement)
        return announcement

    def test_each_audience_reaches_the_right_people(self):
        # The principal is the author; the accountant is staff too.
        north_staff = {"admin", "teacher", "otherteacher", "accountant"}
        cases = [
            ({"audience": "parents"}, {"parent"}),
            ({"audience": "students"}, {"alice", "bob"}),
            ({"audience": "staff"}, north_staff),
            ({"audience": "everyone"}, north_staff | {"alice", "bob", "parent"}),
            ({"audience": "class", "classroom": self.c}, {"alice", "bob", "parent"}),
        ]
        for fields, expected in cases:
            with self.subTest(audience=fields["audience"]):
                self.assertEqual(recipients(self.publish(self.principal, **fields)), expected)

    def test_every_branch_announcement_from_the_super_admin(self):
        announcement = self.publish(self.root, audience="parents", branch=None)
        self.assertEqual(recipients(announcement), {"parent"})
        everyone = self.publish(self.root, audience="students", branch=None)
        self.assertEqual(recipients(everyone), {"alice", "bob", "charlie"})

    def test_who_may_announce(self):
        cases = [
            (self.teacher, {"audience": "class", "classroom": self.c}, True),
            (self.teacher, {"audience": "parents"}, False),  # teachers: their classes only
            (self.foreign_teacher, {"audience": "class", "classroom": self.c}, False),
            (self.admin, {"audience": "everyone", "branch": self.b}, False),  # another branch
            (self.admin, {"audience": "everyone", "branch": None}, False),  # every branch
            (self.e1.student.user, {"audience": "everyone"}, False),
            (self.parent, {"audience": "parents"}, False),
        ]
        for actor, fields, allowed in cases:
            with self.subTest(actor=actor.username, fields=fields):
                if allowed:
                    self.publish(actor, **fields)
                else:
                    with self.assertRaises(PermissionDenied):
                        self.publish(actor, **fields)

    def test_running_the_delivery_twice_notifies_nobody_twice(self):
        announcement = self.publish(self.principal, audience="parents")
        self.assertEqual(deliver_announcement(announcement.pk), 0)
        self.assertEqual(Notification.objects.filter(recipient=self.parent).count(), 1)

    def test_who_reads_which_announcement(self):
        for_parents = self.publish(self.principal, audience="parents")
        for_class = self.publish(self.teacher, audience="class", classroom=self.c)
        cases = [
            (self.parent, {for_parents, for_class}),
            (self.e1.student.user, {for_class}),
            (self.teacher, {for_parents, for_class}),  # staff see what their branch was told
            (self.foreign_teacher, set()),
            (self.foreign_enrollment.student.user, set()),
        ]
        for user, expected in cases:
            with self.subTest(user=user.username):
                self.assertEqual(set(announcements(user)), expected)


class NotifyTests(SchoolTestCase):
    def test_email_goes_once_to_each_person_separately(self):
        people = [self.parent, self.teacher]
        sent = notify(
            people, "results", "results:1", "Results published", "Midterm", "/exams/", email=True
        )
        again = notify(
            people, "results", "results:1", "Results published", "Midterm", "/exams/", email=True
        )
        self.assertEqual((sent, again), (2, 0))
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(
            [m.to for m in mail.outbox], [["parent@example.com"], ["teacher@example.com"]]
        )
        self.assertIn("http://localhost:8000/exams/", mail.outbox[0].body)

    def test_inactive_accounts_get_nothing(self):
        self.parent.is_active = False
        self.parent.save()
        self.assertEqual(notify([self.parent], "results", "results:2", "x"), 0)


class NotificationWebTests(SchoolTestCase):
    def setUp(self):
        notify([self.parent], "results", "results:1", "Midterm results", "", "/exams/")
        notify([self.parent], "announcement", "announcement:9", "Sports day")
        self.client.force_login(self.parent)

    def test_bell_shows_the_unread_count(self):
        page = self.client.get(reverse("notifications")).content.decode()
        self.assertIn('aria-label="Notifications, 2 unread"', page)
        self.assertIn("Midterm results", page)

    def test_opening_marks_read_and_follows_the_link(self):
        notification = Notification.objects.get(key="results:1")
        response = self.client.post(reverse("notification_open", args=[notification.pk]))
        self.assertRedirects(response, "/exams/", fetch_redirect_response=False)
        notification.refresh_from_db()
        self.assertIsNotNone(notification.read_at)

    def test_mark_all_read_and_other_peoples_notifications(self):
        self.client.post(reverse("notifications"))
        self.assertFalse(Notification.objects.filter(read_at__isnull=True).exists())
        other = notify([self.teacher], "results", "results:3", "x")
        theirs = Notification.objects.get(recipient=self.teacher)
        self.assertEqual(other, 1)
        response = self.client.post(reverse("notification_open", args=[theirs.pk]))
        self.assertEqual(response.status_code, 404)

    def test_a_stored_link_to_another_site_is_not_followed(self):
        notify([self.parent], "results", "results:4", "x", url="https://evil.example/")
        notification = Notification.objects.get(key="results:4")
        response = self.client.post(reverse("notification_open", args=[notification.pk]))
        self.assertRedirects(response, reverse("notifications"), fetch_redirect_response=False)

    def test_announcement_pages(self):
        self.assertEqual(self.client.get(reverse("announcements")).status_code, 200)
        self.assertEqual(self.client.get(reverse("announcement_create")).status_code, 403)
        self.client.force_login(self.teacher)
        form = self.client.get(reverse("announcement_create")).context["form"]
        self.assertEqual([value for value, _ in form.fields["audience"].choices], ["class"])
        self.assertNotIn("branch", form.fields)
        response = self.client.post(
            reverse("announcement_create"),
            {"audience": "class", "classroom": self.c.pk, "title": "Trip", "body": "Bring lunch."},
        )
        self.assertRedirects(response, reverse("announcements"))


class CommunicationApiTests(ApiTestCase):
    def test_announcements(self):
        self.as_user(self.principal)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                "/api/v1/announcements/", {"audience": "parents", "title": "PTM", "body": "Sat."}
            )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["branch"], self.a.pk)
        self.as_user(self.parent)
        titles = [a["title"] for a in self.client.get("/api/v1/announcements/").json()["results"]]
        self.assertEqual(titles, ["PTM"])
        self.as_user(self.teacher)
        refused = self.client.post(
            "/api/v1/announcements/", {"audience": "parents", "title": "x", "body": "y"}
        )
        self.assertEqual(refused.status_code, 403)
        foreign = self.client.post(
            "/api/v1/announcements/",
            {"audience": "class", "classroom": self.foreign_class.pk, "title": "x", "body": "y"},
        )
        self.assertIn("classroom", foreign.json()["fields"])

    def test_notifications(self):
        notify([self.parent], "results", "results:1", "Midterm results")
        notify([self.parent], "announcement", "announcement:9", "Sports day")
        notify([self.teacher], "results", "results:1", "Not yours")
        self.as_user(self.parent)
        self.assertEqual(
            self.client.get("/api/v1/notifications/unread-count/").json(), {"unread": 2}
        )
        listed = self.client.get("/api/v1/notifications/?unread=true").json()["results"]
        self.assertEqual({n["title"] for n in listed}, {"Midterm results", "Sports day"})
        read = self.client.post(f"/api/v1/notifications/{listed[0]['id']}/read/").json()
        self.assertIsNotNone(read["read_at"])
        self.assertEqual(
            self.client.get("/api/v1/notifications/unread-count/").json(), {"unread": 1}
        )
        self.client.post("/api/v1/notifications/read-all/")
        self.assertEqual(
            self.client.get("/api/v1/notifications/unread-count/").json(), {"unread": 0}
        )
        theirs = Notification.objects.get(recipient=self.teacher)
        self.assertEqual(self.client.get(f"/api/v1/notifications/{theirs.pk}/").status_code, 404)


class LateAccountTests(SchoolTestCase):
    def test_new_accounts_created_later_do_not_get_old_announcements(self):
        announcement = Announcement(title="Old", body="x", audience="parents", branch=self.a)
        with self.captureOnCommitCallbacks(execute=True):
            publish_announcement(self.principal, announcement)
        User.objects.create_user("late", "late@example.com", PASSWORD, role="parent", branch=self.a)
        self.assertEqual(recipients(announcement), {"parent"})


class AnnouncementRuleTests(SchoolTestCase):
    def test_class_and_classroom_go_together_within_the_branch(self):
        cases = [
            ({"audience": "class"}, "Choose the class"),
            ({"audience": "parents", "classroom": self.c}, "only chosen for a class"),
            ({"audience": "class", "classroom": self.foreign_class}, "in this branch"),
        ]
        for fields, message in cases:
            with self.subTest(fields=fields):
                announcement = Announcement(
                    branch=self.a, title="x", body="y", author=self.root, **fields
                )
                with self.assertRaisesMessage(ValidationError, message):
                    announcement.full_clean()


class BellTests(SchoolTestCase):
    def test_the_bell_partial_shows_the_unread_count_and_keeps_polling(self):
        notify([self.parent], "test", "bell:1", "Fees due")
        self.sign_in(self.parent)
        response = self.client.get(reverse("notification_bell"), HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "partials/bell.html")
        self.assertContains(response, "1 unread")
        self.assertContains(response, 'hx-trigger="every 60s, visibilitychange from:document"')
        self.assertIn("no-store", response["Cache-Control"])

    def test_a_signed_out_bell_stops_polling_instead_of_showing_the_sign_in_page(self):
        response = self.client.get(reverse("notification_bell"), HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 286)  # htmx: stop polling
        self.assertEqual(response.content, b"")

    def test_no_polling_before_the_initial_password_is_changed(self):
        self.parent.must_change_password = True
        self.parent.save(update_fields=["must_change_password"])
        self.sign_in(self.parent)
        page = self.client.get(reverse("password_change"))
        self.assertContains(page, 'id="bell"')
        self.assertNotContains(page, 'hx-trigger="every 60s')
