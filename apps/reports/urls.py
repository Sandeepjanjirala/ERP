from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("students/<int:pk>/report/", views.student_report, name="student_report"),
    path("reports/", views.reports, name="reports"),
    path("activity/", views.audit_log, name="audit"),
]
