from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("branches", views.BranchViewSet, basename="api-branch")
router.register("years", views.AcademicYearViewSet, basename="api-year")
router.register("terms", views.TermViewSet, basename="api-term")
router.register("periods", views.PeriodViewSet, basename="api-period")
router.register("grades", views.GradeViewSet, basename="api-grade")
router.register("classrooms", views.ClassroomViewSet, basename="api-classroom")
router.register("subjects", views.SubjectViewSet, basename="api-subject")
router.register("assignments", views.TeachingAssignmentViewSet, basename="api-assignment")
urlpatterns = [
    path("organization/", views.OrganizationView.as_view(), name="api-organization"),
    path("years/<int:pk>/terms/", views.YearTermsView.as_view(), name="api-year-terms"),
    path(
        "classrooms/<int:pk>/timetable/",
        views.ClassroomTimetableView.as_view(),
        name="api-classroom-timetable",
    ),
    path("timetable/mine/", views.MyTimetableView.as_view(), name="api-my-timetable"),
    *router.urls,
]
