"""Local development: debug pages, SQLite unless DATABASE_URL is set.

Emails print to the console, unless EMAIL_HOST names a mail catcher (Docker uses Mailpit).
"""

from .base import *  # noqa: F403

DEBUG = True
if not SECRET_KEY:
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY or run python setup_local.py.")
DATABASES = {"default": database_config(DATABASE_URL, default_sslmode="prefer")}

# Plain HTTP on localhost.
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False

if not EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# The browsable API (HTML pages at /api/v1/ while signed in) is a development convenience;
# production serves JSON only.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
}
