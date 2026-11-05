"""Version 1 of the REST API. Each app owns its endpoints in apps/<app>/api/urls.py."""

from django.urls import include, path

urlpatterns = [
    path("", include("apps.accounts.api.urls")),
    path("", include("apps.organization.api.urls")),
    path("", include("apps.academics.api.urls")),
    path("", include("apps.students.api.urls")),
    path("", include("apps.attendance.api.urls")),
    path("", include("apps.exams.api.urls")),
    path("", include("apps.reports.api.urls")),
]
