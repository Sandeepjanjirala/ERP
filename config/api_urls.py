"""Version 1 of the REST API. Each app owns its endpoints in apps/<app>/api/urls.py."""

from django.urls import include, path

urlpatterns = [
    path("", include("apps.accounts.api.urls")),
]
