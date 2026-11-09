"""Real-browser tests: Playwright drives Chromium against a live EduNexa server.

The server is Django's live test server with the real middleware, so every page carries the real
Content-Security-Policy. Each test fails if the browser logs a console error or a CSP violation.
htmx, the confirmation dialogs, the charts and the phone layout run exactly as people use them.

Needs `python -m playwright install chromium`; without the browser these tests are skipped.
"""

import os
from datetime import timedelta
from unittest import SkipTest

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client
from django.utils import timezone

from apps.academics.models import (
    AcademicYear,
    Classroom,
    Grade,
    Period,
    TeachingAssignment,
    TimetableSlot,
)
from apps.academics.services import default_terms
from apps.attendance.models import Attendance, AttendanceSession
from apps.attendance.services import save_register
from apps.core.testing import SchoolTestCase
from apps.students.models import Enrollment

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:  # pragma: no cover - only without the dev requirements
    sync_playwright = None


class BrowserTestCase(StaticLiveServerTestCase):
    """A live server with the school fixture, and one Chromium for the whole class."""

    @classmethod
    def setUpClass(cls):
        if sync_playwright is None:
            raise SkipTest("Playwright isn't installed.")
        # Playwright's sync API runs an event loop; Django's ORM calls in the test are still
        # plain synchronous code, so this check is safe to switch off here.
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        super().setUpClass()
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch()
        except Exception as error:  # the browser isn't installed
            cls.playwright.stop()
            super().tearDownClass()
            raise SkipTest(f"Chromium for Playwright isn't installed: {error}") from None

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        super().tearDownClass()

    def setUp(self):
        SchoolTestCase.setUpTestData.__func__(type(self))
        self.problems = []
        self.context = None

    def tearDown(self):
        if self.context:
            self.context.close()
        self.assertEqual(self.problems, [], "the browser logged errors")

    def open_as(self, user, path, **context_options):
        """A page signed in as `user` (the session cookie from Django's test client)."""
        client = Client()
        client.force_login(user)
        self.context = self.browser.new_context(**context_options)
        self.context.add_cookies(
            [
                {
                    "name": "sessionid",
                    "value": client.cookies["sessionid"].value,
                    "url": self.live_server_url,
                }
            ]
        )
        page = self.context.new_page()
        page.on(
            "console",
            lambda message: message.type == "error" and self.problems.append(message.text),
        )
        page.on("pageerror", lambda error: self.problems.append(str(error)))
        page.goto(self.live_server_url + path)
        # A marker that survives htmx swaps but not a page load: proves nothing reloaded.
        page.evaluate("window.notReloaded = true")
        return page

    def assert_not_reloaded(self, page):
        self.assertTrue(page.evaluate("window.notReloaded === true"), "the page reloaded")


class AttendanceTests(BrowserTestCase):
    def register_path(self):
        return f"/attendance/?classroom={self.c.pk}&date={self.today.isoformat()}"

    def test_one_tap_mark_all_and_save_without_a_reload(self):
        page = self.open_as(self.teacher, self.register_path())
        page.get_by_role("button", name="Mark all present").click()
        expect(page.get_by_text("Everyone is marked present.")).to_be_visible()
        # One tap: Bob is absent today.
        page.locator(f"label.status-A:has(input[name='status_{self.e2.pk}'])").click()
        page.get_by_role("button", name="Save daily attendance").click()
        expect(page.get_by_text("Daily attendance saved.")).to_be_visible()
        self.assert_not_reloaded(page)
        statuses = dict(
            Attendance.objects.filter(session__classroom=self.c).values_list(
                "enrollment_id", "status"
            )
        )
        self.assertEqual(statuses, {self.e1.pk: "P", self.e2.pk: "A"})

    def test_the_keyboard_alone_can_take_the_register(self):
        page = self.open_as(self.teacher, self.register_path())
        first = page.locator(f"input[name='status_{self.e1.pk}'][value='P']")
        first.focus()
        page.keyboard.press(" ")  # select Present
        page.keyboard.press("ArrowRight")  # arrow keys move within the group: Absent
        expect(page.locator(f"input[name='status_{self.e1.pk}'][value='A']")).to_be_checked()
        page.locator(f"input[name='status_{self.e2.pk}'][value='P']").focus()
        page.keyboard.press(" ")
        page.get_by_role("button", name="Save daily attendance").focus()
        page.keyboard.press("Enter")
        expect(page.get_by_text("Daily attendance saved.")).to_be_visible()
        self.assertEqual(
            AttendanceSession.objects.get().records.get(enrollment=self.e1).status, "A"
        )

    def test_a_stale_register_shows_the_conflict_in_place(self):
        page = self.open_as(self.teacher, self.register_path())
        # Someone else saves first.
        save_register(self.admin, self.c, self.today, {self.e1.pk: "P", self.e2.pk: "P"}, 0)
        page.get_by_role("button", name="Mark all present").click()
        expect(page.get_by_text("Everyone is marked present.")).to_be_visible()
        page.get_by_role("button", name="Save daily attendance").click()
        expect(page.get_by_text("Another user changed this register")).to_be_visible()
        self.assert_not_reloaded(page)


class TimetableTests(BrowserTestCase):
    def setUp(self):
        super().setUp()
        self.p1 = Period.objects.create(branch=self.a, number=1, starts_at="08:30", ends_at="09:15")
        self.c2 = Classroom.objects.create(
            branch=self.a, year=self.year, grade=self.grade9, section="B"
        )
        self.math_b = TeachingAssignment.objects.create(
            teacher=self.teacher, classroom=self.c2, subject=self.math
        )

    def test_choosing_a_lesson_saves_the_cell_and_clashes_show_in_it(self):
        math_a = TeachingAssignment.objects.get(classroom=self.c, subject=self.math)
        page = self.open_as(self.admin, f"/timetable/{self.c.pk}/")
        expect(page.locator(".no-htmx").first).to_be_hidden()  # htmx is on: no Save buttons
        page.select_option(f"#lesson-1-{self.p1.pk}", str(math_a.pk))
        expect(page.locator(f"#cell-1-{self.p1.pk}")).to_contain_text("Saved")
        self.assertTrue(
            TimetableSlot.objects.filter(classroom=self.c, weekday=1, period=self.p1).exists()
        )
        self.assert_not_reloaded(page)

        page = self.open_as(self.admin, f"/timetable/{self.c2.pk}/")
        page.select_option(f"#lesson-1-{self.p1.pk}", str(self.math_b.pk))
        expect(page.locator(f"#cell-1-{self.p1.pk}")).to_contain_text(
            "already teaches 9-A on Monday"
        )
        self.assertFalse(TimetableSlot.objects.filter(classroom=self.c2).exists())


class FilterAndDialogTests(BrowserTestCase):
    def test_lists_filter_as_you_type(self):
        page = self.open_as(self.admin, "/students/")
        expect(page.locator("#results tbody tr")).to_have_count(2)
        page.fill("#student-search", "alice")
        expect(page.locator("#results tbody tr")).to_have_count(1)
        expect(page.locator("#results")).to_contain_text("alice")
        self.assertIn("q=alice", page.url)  # the address follows, so it can be shared
        self.assert_not_reloaded(page)

    def test_confirmation_dialogs_can_be_cancelled(self):
        next_year = AcademicYear.objects.create(
            name="Next", starts_on=self.year.ends_on + timedelta(days=1), ends_on=self.year.ends_on + timedelta(days=300)
        )  # fmt: skip
        default_terms(next_year)
        grade10 = Grade.objects.create(branch=self.a, name="10", order=10)
        target = Classroom.objects.create(branch=self.a, year=next_year, grade=grade10, section="A")
        page = self.open_as(
            self.principal, f"/students/promotion/?source={self.c.pk}&target={target.pk}"
        )
        page.once("dialog", lambda dialog: dialog.dismiss())
        page.get_by_role("button", name="Move the class on").click()
        page.wait_for_timeout(300)
        self.assertFalse(Enrollment.objects.filter(year=next_year).exists())  # cancelled: nothing
        page.once("dialog", lambda dialog: dialog.accept())
        page.get_by_role("button", name="Move the class on").click()
        expect(page.get_by_text("2 moved up")).to_be_visible()
        self.assertEqual(Enrollment.objects.filter(year=next_year).count(), 2)


class ChartAndLayoutTests(BrowserTestCase):
    def test_charts_redraw_in_the_other_theme(self):
        save_register(self.teacher, self.c, self.today, {self.e1.pk: "P", self.e2.pk: "A"}, 0)
        page = self.open_as(self.admin, "/", color_scheme="light")
        page.wait_for_function(
            "window.Chart && Chart.getChart(document.getElementById('attendance-trend'))"
        )
        colour = "Chart.getChart(document.getElementById('attendance-trend')).data.datasets[0].borderColor"
        before = page.evaluate(colour)
        page.locator("[data-theme-toggle]").click()
        page.wait_for_function(f"{colour} !== '{before}'")
        self.assertNotEqual(page.evaluate(colour), before)
        self.assertEqual(page.evaluate("document.documentElement.dataset.theme"), "dark")

    def test_phone_layout(self):
        phone = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}
        for path in (
            "/",
            f"/attendance/?classroom={self.c.pk}&date={timezone.localdate().isoformat()}",
            f"/timetable/{self.c.pk}/",
        ):
            with self.subTest(path=path):
                page = self.open_as(self.admin, path, **phone)
                overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
                self.assertLessEqual(overflow, 0, "the page scrolls sideways on a phone")
                menu = page.locator("#menu-toggle")
                expect(menu).to_be_visible()
                menu.click()
                expect(menu).to_have_attribute("aria-expanded", "true")
                expect(page.locator("#sidebar")).to_have_class("sidebar open")
                self.context.close()
                self.context = None
