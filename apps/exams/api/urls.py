from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("exams", views.ExamViewSet, basename="api-exam")
urlpatterns = router.urls
