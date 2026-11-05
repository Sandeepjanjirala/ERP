from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("students", views.StudentViewSet, basename="api-student")
urlpatterns = router.urls
