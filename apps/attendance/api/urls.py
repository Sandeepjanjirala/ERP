from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

urlpatterns = [
    path("classrooms/<int:pk>/register/", views.RegisterView.as_view(), name="api-register"),
]

router = SimpleRouter()
router.register("leave-requests", views.LeaveRequestViewSet, basename="api-leave-request")
urlpatterns += router.urls
