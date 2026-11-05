from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("branches", views.BranchViewSet, basename="api-branch")
urlpatterns = router.urls
