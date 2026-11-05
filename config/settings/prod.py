"""Production: refuses to start without a secret key and a PostgreSQL DATABASE_URL."""

from .base import *  # noqa: F403

DEBUG = False
if not SECRET_KEY:
    raise ImproperlyConfigured("Production requires DJANGO_SECRET_KEY.")
if not DATABASE_URL:
    raise ImproperlyConfigured("Production requires DATABASE_URL for PostgreSQL.")
DATABASES = {"default": database_config(DATABASE_URL, default_sslmode="require")}
