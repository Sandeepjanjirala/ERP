from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("students", views.StudentViewSet, basename="api-student")
router.register("enrollments", views.EnrollmentViewSet, basename="api-enrollment")
router.register("student-imports", views.StudentImportViewSet, basename="api-student-import")
urlpatterns = [
    path("classrooms/<int:pk>/promotion/", views.PromotionView.as_view(), name="api-promotion"),
    *router.urls,
]
