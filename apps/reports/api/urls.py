from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

urlpatterns = [
    path("students/<int:pk>/report/", views.StudentReportView.as_view(), name="api-student-report"),
    path(
        "students/<int:pk>/report-card/",
        views.ReportCardView.as_view(),
        name="api-report-card",
    ),
    path("dashboard/", views.DashboardView.as_view(), name="api-dashboard"),
    path("reports/performance/", views.PerformanceView.as_view(), name="api-performance"),
    path(
        "reports/performance/export/",
        views.PerformanceExportView.as_view(),
        name="api-performance-export",
    ),
]

router = SimpleRouter()
router.register("activity", views.ActivityViewSet, basename="api-activity")
urlpatterns += router.urls
