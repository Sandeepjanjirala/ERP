"""Production. Refuses to start unless the settings a real deployment needs are present and
agree with each other, so a mistake shows at startup rather than as broken links or logins.
See docs/DEPLOYMENT.md and deploy/env.production.example.
"""

from urllib.parse import urlparse

from .base import *  # noqa: F403

DEBUG = False


def require(condition, what):
    if not condition:
        raise ImproperlyConfigured(f"Production requires {what}. See docs/DEPLOYMENT.md.")


require(SECRET_KEY, "DJANGO_SECRET_KEY")
require(len(SECRET_KEY) >= 50, "a DJANGO_SECRET_KEY of at least 50 characters")
require(DATABASE_URL, "DATABASE_URL for PostgreSQL")
DATABASES = {"default": database_config(DATABASE_URL, default_sslmode="require")}

require(os.getenv("ALLOWED_HOSTS"), "ALLOWED_HOSTS: the site's hostnames")
site = urlparse(os.getenv("SITE_URL", ""))
require(site.scheme == "https" and site.hostname, "SITE_URL: the https:// address people open")
require(site.hostname in ALLOWED_HOSTS, f"SITE_URL's host ({site.hostname}) in ALLOWED_HOSTS")
require(
    f"https://{site.netloc}" in CSRF_TRUSTED_ORIGINS,
    f"CSRF_TRUSTED_ORIGINS to include https://{site.netloc}",
)
require(REDIS_URL, "REDIS_URL: background jobs and the shared cache")
require(EMAIL_HOST or DEMO_MODE, "EMAIL_HOST: password resets and notices are sent by email")
