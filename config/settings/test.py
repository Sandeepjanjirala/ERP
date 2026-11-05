"""Automated tests: deterministic, fast, and independent of a developer's local services."""

from .base import *  # noqa: F403

DEBUG = False
SECRET_KEY = SECRET_KEY or "test-only-secret-key-never-used-by-a-real-environment"
# SQLite in memory by default; CI sets DATABASE_URL to run the same tests on PostgreSQL.
DATABASES = {"default": database_config(DATABASE_URL, default_sslmode="prefer")}

SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
# Serve static files without requiring collectstatic first.
WHITENOISE_AUTOREFRESH = True
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
# The API accepts JSON only, so DRF's test client sends JSON unless told otherwise.
REST_FRAMEWORK = {**REST_FRAMEWORK, "TEST_REQUEST_DEFAULT_FORMAT": "json"}
# A fast hash for test accounts only. Real environments keep Django's default PBKDF2.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
