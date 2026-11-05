from django.urls import path

from . import views

urlpatterns = [
    path("students/<int:pk>/report/", views.StudentReportView.as_view(), name="api-student-report"),
]
