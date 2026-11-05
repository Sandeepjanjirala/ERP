from django.urls import include, path

# Each app owns its URLs. The paths are unchanged from the single-app version, so existing links
# keep working. Order matters in one place: students (setup/enrollment/new/) must come before
# academics (the generic setup/<kind>/new/).
urlpatterns = [
    path("", include("apps.core.urls")),
    path("", include("apps.accounts.urls")),
    path("", include("apps.reports.urls")),
    path("", include("apps.students.urls")),
    path("", include("apps.academics.urls")),
    path("", include("apps.attendance.urls")),
    path("", include("apps.exams.urls")),
]
