from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("students/<int:pk>/report/", views.student_report, name="student_report"),
    path("students/<int:pk>/report-card.pdf", views.report_card, name="report_card"),
    path("students/<int:pk>/records.zip", views.records, name="student_records"),
    path("reports/", views.reports, name="reports"),
    path("search/", views.search, name="search"),
    path("activity/", views.audit_log, name="audit"),
]
