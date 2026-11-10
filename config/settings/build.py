"""Building the Docker image: only `collectstatic` runs with these settings, so the image
carries its static files. Never used to serve requests; nothing here is a real secret."""

from .base import *  # noqa: F403

DEBUG = False
SECRET_KEY = "build-only-not-a-secret-never-used-to-serve-requests"
DATABASES = {"default": database_config("", default_sslmode="disable")}
