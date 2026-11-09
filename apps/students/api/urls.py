from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("students", views.StudentViewSet, basename="api-student")
router.register("enrollments", views.EnrollmentViewSet, basename="api-enrollment")
router.register("student-imports", views.StudentImportViewSet, basename="api-student-import")
urlpatterns = router.urls
