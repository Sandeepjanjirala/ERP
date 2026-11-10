"""The production rehearsal: the real deploy/ stack on this machine, then everything checked.

    python e2e/rehearse_deploy.py [--keep]

It builds the image and starts deploy/compose.production.yaml (Caddy with HTTPS from its own
local certificate authority, Gunicorn, a Celery worker and scheduler, PostgreSQL, Redis) under
production settings, plus Mailpit to catch emails (deploy/compose.rehearsal.yaml). Secrets are
generated for the run and thrown away. Then:

1. the release steps: migrate, then Django's deployment checklist (warnings fail);
2. HTTPS and headers: HTTP redirects to HTTPS, a certificate chain that verifies, HSTS, the
   CSP, secure cookies, no Server header, a request id;
3. the 69 API checks (e2e/api_checks.py) over HTTPS, with the worker and Mailpit;
4. a real browser signs in as every role and opens their pages: no console errors or CSP
   violations;
5. the backup and restore drill: deploy/backup.sh, data lost, deploy/restore.sh, and every
   table compared with the backup row for row.

Needs Docker, bash, ports 80 and 443 free, and Playwright's Chromium. The stack is removed at
the end (--keep leaves it running at https://edunexa.localhost). Never run it on a server.
"""

import argparse
import os
import re
import runpy
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookies import SimpleCookie
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "deploy"
PROJECT = "edunexa-rehearsal"
DOMAIN = "edunexa.localhost"
SITE = f"https://{DOMAIN}"
MAILPIT = "http://127.0.0.1:18025"
ROLES = {
    "superadmin": ["/", "/activity/", "/setup/", "/users/", "/search/?q=ra"],
    "admin.madhapur": ["/", "/students/", "/fees/", "/timetable/", "/students/promotion/"],
    "principal.madhapur": ["/", "/exams/", "/reports/", "/leave/"],
    "teacher.madhapur": ["/", "/attendance/", "/timetable/mine/", "/exams/"],
    "accountant.madhapur": ["/", "/fees/", "/fees/collections/", "/fees/review/"],
    "student1.madhapur": ["/", "/timetable/", "/announcements/"],
    "parent1.madhapur": ["/", "/fees/", "/leave/", "/notifications/"],
}
failures = []


def bash():
    """bash for the deploy scripts. On Windows, Git's (a bare "bash" may be WSL's, which can't
    see Windows paths)."""
    if os.name == "nt":
        for folder in Path(shutil.which("git")).resolve().parents:
            if (folder / "bin" / "bash.exe").exists() and (folder / "usr").is_dir():
                return str(folder / "bin" / "bash.exe")
    return shutil.which("bash")


def check(ok, what):
    print(("  ok    " if ok else "  FAIL  ") + what)
    if not ok:
        failures.append(what)


def step(title):
    print(f"\n== {title}")


class Stack:
    def __init__(self, env_file):
        self.env_file = env_file
        self.args = [
            "-p",
            PROJECT,
            "--env-file",
            str(env_file),
            "-f",
            "compose.production.yaml",
            "-f",
            "compose.rehearsal.yaml",
        ]
        self.env = {
            **os.environ,
            "EDUNEXA_ENV_FILE": str(env_file),
            "COMPOSE_PROJECT_NAME": PROJECT,
        }

    def run(self, *args, capture=False, check=True, stdin=None):
        result = subprocess.run(
            ["docker", "compose", *self.args, *args],
            cwd=DEPLOY,
            env=self.env,
            text=True,
            input=stdin,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
        )
        if check and result.returncode != 0:
            raise SystemExit(f"docker compose {' '.join(args)} failed:\n{result.stderr or ''}")
        return result

    def manage(self, *args, extra_env=(), capture=True):
        flags = [item for name in extra_env for item in ("-e", name)]
        return self.run(
            "run", "--rm", "--no-deps", *flags, "web", "python", "manage.py", *args, capture=capture
        )

    def sql(self, query):
        return self.run(
            "exec",
            "-T",
            "db",
            "psql",
            "-U",
            "edunexa",
            "-d",
            "edunexa",
            "-At",
            "-c",
            query,
            capture=True,
        ).stdout

    def script(self, name, *args):
        """Run deploy/<name> as on the server, pointed at this rehearsal's stack."""
        extra = " ".join(self.args[:4] + self.args[6:])  # -p, --env-file, the rehearsal file
        result = subprocess.run(
            [bash(), (DEPLOY / name).as_posix(), *args],
            env={**self.env, "COMPOSE_EXTRA": extra},
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise SystemExit(f"{name} failed:\n{result.stdout}\n{result.stderr}")
        return result.stdout


def write_env(folder):
    values = {
        "SITE_DOMAIN": DOMAIN,
        "SITE_URL": SITE,
        "ALLOWED_HOSTS": DOMAIN,
        "CSRF_TRUSTED_ORIGINS": SITE,
        "CADDY_TLS": "internal",
        "DJANGO_SECRET_KEY": secrets.token_urlsafe(60),
        "POSTGRES_PASSWORD": secrets.token_urlsafe(24),
        "EMAIL_HOST": "mailpit",
        "DEFAULT_FROM_EMAIL": "EduNexa rehearsal <noreply@example.invalid>",
        "WEB_CONCURRENCY": "2",
    }
    path = Path(folder) / "rehearsal.env"
    path.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
    return path


def resolve_domain_locally():
    """Python on Windows doesn't resolve *.localhost (browsers do): send it to this machine."""
    original = socket.getaddrinfo

    def getaddrinfo(host, *args, **kwargs):
        return original("127.0.0.1" if host == DOMAIN else host, *args, **kwargs)

    socket.getaddrinfo = getaddrinfo


def trust(ca_file):
    """Verify HTTPS against Caddy's local certificate authority (and nothing else)."""
    context = ssl.create_default_context(cafile=str(ca_file))
    ssl._create_default_https_context = lambda: context  # noqa: SLF001 - used by urllib
    return context


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch(url, data=None, headers=None):
    opener = urllib.request.build_opener(NoRedirect)
    request = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        return opener.open(request, timeout=30)
    except urllib.error.HTTPError as error:
        return error


def https_checks(context):
    step("HTTPS and security headers")
    response = fetch(f"http://{DOMAIN}/accounts/login/")
    check(
        response.status in (301, 308) and response.headers["Location"] == f"{SITE}/accounts/login/",
        f"plain HTTP redirects to HTTPS ({response.status})",
    )
    with socket.create_connection(("127.0.0.1", 443)) as raw:
        with context.wrap_socket(raw, server_hostname=DOMAIN) as tls:
            check(
                tls.version() in ("TLSv1.2", "TLSv1.3"),
                f"the certificate verifies; {tls.version()}",
            )
    page = fetch(f"{SITE}/accounts/login/")
    headers = page.headers
    check(page.status == 200, "the sign-in page answers over HTTPS")
    check("max-age=31536000" in (headers["Strict-Transport-Security"] or ""), "HSTS for a year")
    check(
        "script-src 'self'" in (headers["Content-Security-Policy"] or ""),
        "a strict Content-Security-Policy",
    )
    check(headers["X-Frame-Options"] == "DENY", "framing refused")
    check(headers["X-Content-Type-Options"] == "nosniff", "no content sniffing")
    check(bool(headers["Referrer-Policy"]), "a referrer policy")
    check(re.fullmatch(r"[0-9a-f]{32}", headers["X-Request-ID"] or "") is not None, "a request id")
    check(headers["Server"] is None, "no Server header")
    cookies = headers.get_all("Set-Cookie") or []
    check(any("csrftoken" in c and "Secure" in c for c in cookies), "the CSRF cookie is Secure")
    check(fetch(f"{SITE}/health/").status == 200, "/health/ answers")
    check(fetch(f"{SITE}/api/v1/students/").status == 401, "the API needs a token")
    return page


def session_cookie_check(password):
    login = fetch(f"{SITE}/accounts/login/")
    token = SimpleCookie(";".join(c.split(";")[0] for c in login.headers.get_all("Set-Cookie")))[
        "csrftoken"
    ].value
    form = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', login.read().decode()).group(1)
    body = urllib.parse.urlencode(
        {"csrfmiddlewaretoken": form, "username": "teacher.madhapur", "password": password}
    )
    response = fetch(
        f"{SITE}/accounts/login/",
        data=body.encode(),
        headers={
            "Cookie": f"csrftoken={token}",
            "Referer": f"{SITE}/accounts/login/",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    session = [
        c for c in response.headers.get_all("Set-Cookie") or [] if c.startswith("sessionid=")
    ]
    check(response.status == 302 and bool(session), "signing in over HTTPS works")
    check(
        bool(session)
        and all(flag in session[0] for flag in ("Secure", "HttpOnly", "SameSite=Lax")),
        "the session cookie is Secure, HttpOnly and SameSite=Lax",
    )


def api_checks(password):
    step("69 API checks over HTTPS (e2e/api_checks.py)")
    argv = sys.argv
    sys.argv = ["api_checks.py", SITE, password, MAILPIT]
    try:
        runpy.run_path(str(ROOT / "e2e" / "api_checks.py"), run_name="__main__")
        code = 0
    except SystemExit as exit_:
        code = exit_.code or 0
    finally:
        sys.argv = argv
    check(code == 0, "the API checks passed")


def browser_checks(password):
    step("A real browser, every role, under the production CSP")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for username, paths in ROLES.items():
            # Chromium resolves *.localhost itself; Caddy's local CA isn't in its store.
            context = browser.new_context(ignore_https_errors=True)
            page = context.new_page()
            problems = []
            page.on("console", lambda m, p=problems: m.type == "error" and p.append(m.text))
            page.on("pageerror", lambda e, p=problems: p.append(str(e)))
            page.goto(f"{SITE}/accounts/login/")
            page.fill("#id_username", username)
            page.fill("#id_password", password)
            page.click("button[type=submit]")
            page.wait_for_load_state("networkidle")
            statuses = []
            for path in paths:
                response = page.goto(SITE + path)
                page.wait_for_load_state("networkidle")
                statuses.append(response.status)
            check(
                statuses == [200] * len(paths) and not problems,
                f"{username}: {len(paths)} pages, statuses {sorted(set(statuses))}, "
                f"{len(problems)} console problems {problems[:2]}",
            )
            context.close()
        browser.close()


def fingerprint(stack):
    """Every table's rows, hashed: equal fingerprints mean equal data."""
    tables = stack.sql(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1"
    ).split()
    query = " UNION ALL ".join(
        f"SELECT '{t}', count(*), md5(coalesce(string_agg(x::text, '|' ORDER BY x::text), '')) FROM \"{t}\" x"
        for t in tables
    )
    return dict((line.split("|")[0], line) for line in stack.sql(query).splitlines())


def backup_restore_drill(stack):
    step("Backup and restore drill (deploy/backup.sh, deploy/restore.sh)")
    before = fingerprint(stack)
    archive = stack.script("backup.sh").strip().splitlines()[-1]
    check(
        archive.startswith("backups/edunexa-") and (DEPLOY / archive).stat().st_size > 0,
        f"backup.sh wrote and verified {archive}",
    )
    stack.sql("TRUNCATE attendance_attendance, exams_mark CASCADE; DELETE FROM django_session;")
    lost = fingerprint(stack)
    check(lost != before, "data lost (attendance and marks emptied)")
    stack.script("restore.sh", archive, "--yes")
    after = fingerprint(stack)
    changed = sorted(t for t in before if before[t] != after.get(t))
    rows = sum(int(line.split("|")[1]) for line in before.values())
    check(
        not changed,
        f"every table equals the backup after restore ({len(before)} tables, {rows} rows)"
        + (f"; differs: {changed}" if changed else ""),
    )
    check(fetch(f"{SITE}/health/").status == 200, "the app serves again after the restore")
    kept = stack.sql(
        "SELECT datname FROM pg_database WHERE datname LIKE 'edunexa_replaced_%'"
    ).split()
    check(len(kept) == 1, "the replaced database is kept for rollback")
    (DEPLOY / archive).unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--keep", action="store_true", help="leave the stack running")
    options = parser.parse_args()
    folder = tempfile.mkdtemp(prefix="edunexa-rehearsal-")
    stack = Stack(write_env(folder))
    started = time.monotonic()
    try:
        step("Build and start the production stack")
        stack.run("build", "--quiet")
        stack.run("up", "--detach", "--wait", "db", "redis", "mailpit")
        print("  release step: migrate, then the deployment checklist")
        stack.manage("migrate", "--noinput")
        result = stack.manage("check", "--deploy", "--fail-level", "WARNING")
        check(result.returncode == 0, "manage.py check --deploy: no warnings")
        seeding = time.monotonic()
        seed = stack.manage("seed_demo", "--size", "small", extra_env=["DEMO_MODE=1"]).stdout
        password = re.search(r"Demo password for all accounts: (\S+)", seed).group(1)
        print(f"  synthetic data seeded in {time.monotonic() - seeding:.0f}s")
        stack.run("up", "--detach", "--wait")
        jobs = stack.run(
            "exec", "-T", "web", "python", "manage.py", "check_jobs", capture=True, check=False
        )
        check(jobs.returncode == 0, "the Celery worker takes jobs (check_jobs)")
        ca = Path(folder) / "caddy-root.crt"
        ca.write_text(
            stack.run(
                "exec",
                "-T",
                "caddy",
                "cat",
                "/data/caddy/pki/authorities/local/root.crt",
                capture=True,
            ).stdout,
            encoding="utf-8",
        )
        resolve_domain_locally()
        context = trust(ca)
        https_checks(context)
        session_cookie_check(password)
        api_checks(password)
        browser_checks(password)
        backup_restore_drill(stack)
    finally:
        if failures:
            stack.run("logs", "--tail", "60", check=False)
        if not options.keep:
            stack.run("down", "--volumes", "--remove-orphans", check=False, capture=True)
    print(
        f"\n{'FAILED: ' + str(len(failures)) if failures else 'All rehearsal checks passed'}"
        f" ({time.monotonic() - started:.0f}s)"
    )
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
