from django.contrib.auth import update_session_auth_hash
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import generics, serializers
from rest_framework.exceptions import Throttled
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from apps.audit.services import audit

from ..models import LoginAttempt
from ..services import change_password
from ..throttling import throttle
from .serializers import (
    MeSerializer,
    PasswordChangeSerializer,
    TokenObtainSerializer,
    TokenPairSerializer,
)


class TokenObtainView(TokenObtainPairView):
    """Sign in. Shares the web sign-in's per-username limit: 8 attempts in 15 minutes."""

    serializer_class = TokenObtainSerializer

    @extend_schema(
        responses=inline_serializer(
            "TokenObtainResponse",
            {
                "access": serializers.CharField(),
                "refresh": serializers.CharField(),
                "must_change_password": serializers.BooleanField(),
            },
        )
    )
    def post(self, request, *args, **kwargs):
        allowed, key = throttle("portal-login", str(request.data.get("username", "")))
        if not allowed:
            raise Throttled(wait=15 * 60, detail="Too many sign-in attempts. Try again later.")
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        LoginAttempt.objects.filter(pk=key).delete()
        user = serializer.user
        audit(user, user.branch, "account.login", user.username, {"via": "api"})
        return Response(serializer.validated_data)


class MeView(generics.RetrieveAPIView):
    """The signed-in user: role, branch, and whether they must change their password first."""

    serializer_class = MeSerializer
    allow_before_password_change = True

    def get_object(self):
        return self.request.user


class PasswordChangeView(generics.GenericAPIView):
    """Replace your password. Every earlier token stops working, so a fresh pair is returned."""

    serializer_class = PasswordChangeSerializer
    allow_before_password_change = True

    @extend_schema(responses=TokenPairSerializer)
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = change_password(
            request.user,
            serializer.validated_data["current_password"],
            serializer.validated_data["new_password"],
        )
        update_session_auth_hash(request, user)  # keeps a browsable-API session signed in
        refresh = RefreshToken.for_user(user)
        return Response({"access": str(refresh.access_token), "refresh": str(refresh)})
