from django.urls import path
from rest_framework.routers import SimpleRouter
from rest_framework_simplejwt.views import TokenBlacklistView, TokenRefreshView

from . import views

urlpatterns = [
    path("auth/token/", views.TokenObtainView.as_view(), name="api-token"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="api-token-refresh"),
    path("auth/logout/", TokenBlacklistView.as_view(), name="api-logout"),
    path("me/", views.MeView.as_view(), name="api-me"),
    path("me/password/", views.PasswordChangeView.as_view(), name="api-password-change"),
]

router = SimpleRouter()
router.register("people", views.PeopleViewSet, basename="api-person")
urlpatterns += router.urls
