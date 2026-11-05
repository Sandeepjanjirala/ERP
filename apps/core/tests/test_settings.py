import os
import secrets
import subprocess
import sys

from django.conf import settings
from django.test import SimpleTestCase


class ProductionSettingsTests(SimpleTestCase):
    """Production settings fail fast instead of starting with unsafe defaults."""

    def manage(self, *args, **env):
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in ("DJANGO_SECRET_KEY", "DATABASE_URL", "DJANGO_SETTINGS_MODULE")
        }
        environment.update(
            DJANGO_SETTINGS_MODULE="config.settings.prod",
            DJANGO_ENV_FILE=str(settings.BASE_DIR / "no-such-file.env"),  # ignore the local .env
            **env,
        )
        return subprocess.run(
            [sys.executable, "manage.py", *args],
            cwd=settings.BASE_DIR,
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_refuses_to_start_without_secret_key(self):
        result = self.manage("check", DATABASE_URL="postgresql://app:pw@db.example.com/edunexa")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Production requires DJANGO_SECRET_KEY", result.stderr)

    def test_refuses_to_start_without_postgres(self):
        result = self.manage("check", DJANGO_SECRET_KEY=secrets.token_urlsafe(60))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Production requires DATABASE_URL", result.stderr)

    def test_passes_django_deployment_checklist(self):
        result = self.manage(
            "check",
            "--deploy",
            "--fail-level",
            "WARNING",
            DJANGO_SECRET_KEY=secrets.token_urlsafe(60),
            DATABASE_URL="postgresql://app:pw@db.example.com/edunexa",
            ALLOWED_HOSTS="edunexa.example.com",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
