from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("exams", views.ExamViewSet, basename="api-exam")
router.register("grading-scales", views.GradingScaleViewSet, basename="api-grading-scale")
urlpatterns = router.urls
