from django.urls import path

from . import views

urlpatterns = [
    path("students/", views.student_list, name="students"),
    path("students/new/", views.student_create, name="student_create"),
    # Enrollment lives with students; the URL keeps its place under Academic setup.
    path("setup/enrollment/new/", views.enrollment_create, name="enrollment_create"),
]
