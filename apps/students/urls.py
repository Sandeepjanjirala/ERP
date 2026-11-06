from django.urls import path

from . import views

urlpatterns = [
    path("students/", views.student_list, name="students"),
    path("students/new/", views.student_create, name="student_create"),
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
