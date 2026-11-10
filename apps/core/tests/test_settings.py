import logging
import os
import secrets
import subprocess
import sys

from django.conf import settings
from django.test import SimpleTestCase

# Never inherited from the shell running the tests.
PRODUCTION_VARIABLES = (
    "DJANGO_SETTINGS_MODULE",
    "DJANGO_SECRET_KEY",
    "DATABASE_URL",
    "ALLOWED_HOSTS",
    "SITE_URL",
    "CSRF_TRUSTED_ORIGINS",
    "REDIS_URL",
    "EMAIL_HOST",
    "DEMO_MODE",
    "RAZORPAY_KEY_ID",
)


class ProductionSettingsTests(SimpleTestCase):
    """Production settings fail fast instead of starting with unsafe defaults."""

    def manage(self, *args, **env):
        environment = {
            key: value for key, value in os.environ.items() if key not in PRODUCTION_VARIABLES
        }
        environment.update(
            DJANGO_SETTINGS_MODULE="config.settings.prod",
            DJANGO_ENV_FILE=str(settings.BASE_DIR / "no-such-file.env"),  # ignore the local .env
        )
        environment.update(env)
        return subprocess.run(
            [sys.executable, "manage.py", *args],
            cwd=settings.BASE_DIR,
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def production(self, **overrides):
        """A complete production environment (values for a check only), with changes."""
        env = {
            "DJANGO_SECRET_KEY": secrets.token_urlsafe(60),
            "DATABASE_URL": "postgresql://app:pw@db.example.com/edunexa",
            "ALLOWED_HOSTS": "edunexa.example.com",
            "SITE_URL": "https://edunexa.example.com",
            "CSRF_TRUSTED_ORIGINS": "https://edunexa.example.com",
            "REDIS_URL": "redis://redis.example.com:6379/0",
            "EMAIL_HOST": "smtp.example.com",
        }
        env.update(overrides)
        return {key: value for key, value in env.items() if value is not None}

    def test_refuses_to_start_without_what_production_needs(self):
        cases = [
            ({"DJANGO_SECRET_KEY": None}, "Production requires DJANGO_SECRET_KEY"),
            ({"DJANGO_SECRET_KEY": "too-short"}, "at least 50 characters"),
            ({"DATABASE_URL": None}, "Production requires DATABASE_URL"),
            ({"ALLOWED_HOSTS": None}, "ALLOWED_HOSTS"),
            ({"SITE_URL": None}, "SITE_URL: the https:// address"),
            ({"SITE_URL": "http://edunexa.example.com"}, "SITE_URL: the https:// address"),
            ({"SITE_URL": "https://other.example.com"}, "(other.example.com) in ALLOWED_HOSTS"),
            ({"CSRF_TRUSTED_ORIGINS": None}, "CSRF_TRUSTED_ORIGINS to include"),
            ({"REDIS_URL": None}, "REDIS_URL"),
            ({"EMAIL_HOST": None}, "EMAIL_HOST"),
        ]
        for overrides, message in cases:
            with self.subTest(overrides=overrides):
                result = self.manage("check", **self.production(**overrides))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)

    def test_passes_django_deployment_checklist(self):
        result = self.manage("check", "--deploy", "--fail-level", "WARNING", **self.production())
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_demo_mode_never_sends_email_and_takes_sandbox_payments_only(self):
        show = (
            "from django.conf import settings; "
            "print(settings.EMAIL_BACKEND, settings.PAYMENT_GATEWAY, "
            "'reset-demo' in settings.CELERY_BEAT_SCHEDULE)"
        )
        demo = self.manage("shell", "-c", show, **self.production(EMAIL_HOST=None, DEMO_MODE="1"))
        self.assertEqual(demo.returncode, 0, demo.stderr)
        self.assertEqual(
            demo.stdout.split()[-3:],
            ["django.core.mail.backends.console.EmailBackend", "sandbox", "True"],
        )
        school = self.manage("shell", "-c", show, **self.production())
        self.assertEqual(school.stdout.split()[-1], "False")  # no reset scheduled
        refused = self.manage(
            "check", **self.production(DEMO_MODE="1", RAZORPAY_KEY_ID="rzp_test_x")
        )
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("Sandbox only", refused.stderr)

    def test_the_image_build_settings_collect_static_files(self):
        """The Dockerfile runs collectstatic with config.settings.build: no secrets needed."""
        result = self.manage("check", DJANGO_SETTINGS_MODULE="config.settings.build")
        self.assertEqual(result.returncode, 0, result.stderr)


class LoggingTests(SimpleTestCase):
    def test_log_lines_carry_the_request_id(self):
        from apps.core.request_id import RequestIDLogFilter, _current

        record = logging.LogRecord("x", logging.INFO, __file__, 1, "hello", None, None)
        RequestIDLogFilter().filter(record)
        self.assertEqual(record.request_id, "-")
        token = _current.set("abc123")
        try:
            RequestIDLogFilter().filter(record)
        finally:
            _current.reset(token)
        self.assertEqual(record.request_id, "abc123")
        self.assertIn("[%(request_id)s]", settings.LOGGING["formatters"]["line"]["format"])
