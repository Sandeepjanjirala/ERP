"""Regenerate the README's screenshots (docs/screenshots/) from a running EduNexa with the full
demo data (`manage.py seed_demo`, not in demo mode, so no demo banner):

    python e2e/screenshots.py BASE_URL DEMO_PASSWORD
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = ""

OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
DESKTOP = {"viewport": {"width": 1366, "height": 860}}
PHONE = {
    "viewport": {"width": 390, "height": 844},
    "is_mobile": True,
    "has_touch": True,
    "device_scale_factor": 2,
}


def record(list_path, pattern):
    """The first link on a list page whose address matches `pattern` (a JS regex)."""

    def find(page):
        page.goto(BASE + list_path)
        return page.evaluate(
            "pattern => [...document.querySelectorAll('#main a')].map(a => a.getAttribute('href'))"
            ".find(href => new RegExp(pattern).test(href))",
            pattern,
        )

    return find


def register(page):
    """Today's register for the teacher's first class."""
    page.goto(BASE + "/attendance/")
    classroom = page.eval_on_selector(
        "select[name=classroom]", "s => [...s.options].find(o => o.value).value"
    )
    day = page.eval_on_selector("input[name=date]", "i => i.value")
    return f"/attendance/?classroom={classroom}&date={day}"


# name, username (None: signed out), the page (or how to find it), browser options
SHOTS = [
    ("sign-in", None, "/accounts/login/", {}),
    ("dashboard", "admin.madhapur", "/", {}),
    ("exam-review", "principal.madhapur", record("/exams/?status=submitted", r"^/exams/\d+/$"), {}),
    (
        "student-report-dark",
        "teacher.madhapur",
        record("/students/", r"/report/$"),
        {"color_scheme": "dark"},
    ),
    ("attendance", "teacher.madhapur", register, {}),
    ("timetable", "admin.madhapur", record("/timetable/", r"^/timetable/\d+/$"), {}),
    ("search", "admin.madhapur", "/search/?q=ra", {}),
    ("parent-phone", "parent1.madhapur", "/", PHONE),
    ("api-docs", None, "/api/docs/", {}),
]


def main():
    global BASE
    BASE, password = sys.argv[1].rstrip("/"), sys.argv[2]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for name, username, target, options in SHOTS:
            context = browser.new_context(**{**DESKTOP, "color_scheme": "light", **options})
            page = context.new_page()
            if username:
                page.goto(BASE + "/accounts/login/")
                page.fill("#id_username", username)
                page.fill("#id_password", password)
                page.click("button[type=submit]")
                page.wait_for_load_state("networkidle")
            path = target(page) if callable(target) else target
            page.goto(BASE + path)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(800)  # charts finish their animation
            page.screenshot(path=OUT / f"{name}.png")
            print(f"{name}.png  {path}")
            context.close()
        browser.close()


if __name__ == "__main__":
    main()
