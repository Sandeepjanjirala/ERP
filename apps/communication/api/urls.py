from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("announcements", views.AnnouncementViewSet, basename="api-announcement")
router.register("notifications", views.NotificationViewSet, basename="api-notification")
urlpatterns = router.urls
