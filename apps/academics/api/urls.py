from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("years", views.AcademicYearViewSet, basename="api-year")
router.register("classrooms", views.ClassroomViewSet, basename="api-classroom")
router.register("subjects", views.SubjectViewSet, basename="api-subject")
router.register("assignments", views.TeachingAssignmentViewSet, basename="api-assignment")
urlpatterns = router.urls
