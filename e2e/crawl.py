"""Open every page a role can reach in a real browser and report console errors and CSP
violations (the policy allows no inline scripts or styles, so a stray one shows up here).

    python e2e/crawl.py BASE_URL PASSWORD [USERNAME ...]

From each signed-in page it follows the sidebar's links, then the first link into a record
on each of those pages (a student report, an invoice, an exam), staying on the site.
Used by e2e/rehearse_deploy.py for every role.
"""

import sys
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

USERS = [
    "superadmin",
    "admin.madhapur",
    "principal.madhapur",
    "teacher.madhapur",
    "accountant.madhapur",
    "student1.madhapur",
    "parent1.madhapur",
]
# Links into a record on a list page; a crawl opens the first of each.
RECORD_LINKS = (
    "a[href*='/report/']",
    "a[href^='/fees/invoices/']",
    "a[href^='/exams/'][href$='/']",
    "a[href^='/timetable/'][href$='/']",
)
SKIP = ("/accounts/logout/", ".pdf", ".zip", "format=csv", "/template/")


def crawl(browser, base, username, password, **context_options):
    """Returns (pages opened, problems): problems are (path, message) pairs."""
    context = browser.new_context(**context_options)
    page = context.new_page()
    problems, current = [], {"path": "/accounts/login/"}
    page.on("console", lambda m: m.type == "error" and problems.append((current["path"], m.text)))
    page.on("pageerror", lambda e: problems.append((current["path"], str(e))))
    page.goto(f"{base}/accounts/login/")
    page.fill("#id_username", username)
    page.fill("#id_password", password)
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")

    def visit(path):
        current["path"] = path
        response = page.goto(base + path)
        page.wait_for_load_state("networkidle")
        if response is None or response.status >= 400:
            problems.append((path, f"HTTP {response.status if response else '?'}"))

    def links(selector):
        hrefs = page.eval_on_selector_all(selector, "els => els.map(e => e.getAttribute('href'))")
        return [h for h in hrefs if h and h.startswith("/") and not any(s in h for s in SKIP)]

    seen = []
    for path in dict.fromkeys(["/", *links("#sidebar a")]):
        visit(path)
        seen.append(path)
        for selector in RECORD_LINKS:
            found = [h for h in links(f"#main {selector}") if h not in seen]
            if found:
                visit(found[0])
                seen.append(found[0])
                visit(path)  # back to the list for the next kind of record
    context.close()
    return seen, problems


def main():
    base, password, *users = sys.argv[1:]
    base = base.rstrip("/")
    failed = False
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for username in users or USERS:
            secure = urlparse(base).scheme == "https"
            seen, problems = crawl(browser, base, username, password, ignore_https_errors=secure)
            print(f"{'ok  ' if not problems else 'FAIL'} {username}: {len(seen)} pages")
            for path, message in problems:
                print(f"       {path}: {message[:200]}")
            failed = failed or bool(problems)
        browser.close()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
