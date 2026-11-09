from django.urls import path

from . import views

urlpatterns = [
    path("students/", views.student_list, name="students"),
    path("students/new/", views.student_create, name="student_create"),
    path("students/import/", views.student_import, name="student_import"),
    path("students/promotion/", views.promotion, name="promotion"),
    path(
        "students/import/template/",
        views.student_import_template,
        name="student_import_template",
    ),
    path("students/import/<int:pk>/", views.student_import_preview, name="student_import_preview"),
    path(
        "students/import/<int:pk>/confirm/",
        views.student_import_confirm,
        name="student_import_confirm",
    ),
    path("students/<int:pk>/guardians/new/", views.guardian_create, name="guardian_create"),
    path("students/<int:pk>/guardians/link/", views.guardian_link, name="guardian_link"),
    path(
        "students/<int:pk>/guardians/<int:link_pk>/primary/",
        views.guardian_make_primary,
        name="guardian_make_primary",
    ),
    # Enrollment lives with students; the URL keeps its place under Academic setup.
    path("setup/enrollment/new/", views.enrollment_create, name="enrollment_create"),
]
