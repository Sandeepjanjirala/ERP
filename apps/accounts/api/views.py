from django.contrib.auth import update_session_auth_hash
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import generics, mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import Throttled
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from apps.audit.services import audit
from apps.core.api.permissions import role_in

from ..models import LoginAttempt, User
from ..selectors import branch_accounts, people
from ..services import change_password, create_account, toggle_access, update_contact_details
from ..throttling import throttle
from .serializers import (
    ContactDetailsSerializer,
    MeSerializer,
    PasswordChangeSerializer,
    PeopleSerializer,
    StaffAccountCreateSerializer,
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


class PeopleViewSet(
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.ReadOnlyModelViewSet,
):
    """People & access. Leaders read the list; super and branch admins manage accounts.

    Each row says whether you may edit it or change its access, from the same policies the
    services enforce. Contact edits (PATCH) can change only name and email.
    """

    queryset = User.objects.none()  # for the schema; get_queryset() is the real scope
    filterset_fields = ["role", "is_active"]
    search_fields = ["username", "first_name", "last_name", "email"]
    ordering_fields = ["username", "first_name", "last_name", "role"]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        if self.action in ("list", "retrieve"):
            return people(self.request.user)
        # Managing: only accounts in your branches (super admins: all branch accounts).
        return branch_accounts(self.request.user).order_by("pk")

    def get_permissions(self):
        # Like the web: leaders see People & access; only managers change accounts.
        roles = User.LEADERS if self.action in ("list", "retrieve") else User.MANAGERS
        return [role_in(*roles)()]

    def get_serializer_class(self):
        return {
            "create": StaffAccountCreateSerializer,
            "partial_update": ContactDetailsSerializer,
        }.get(self.action, PeopleSerializer)

    def person_response(self, person, status_code=status.HTTP_200_OK):
        data = PeopleSerializer(person, context=self.get_serializer_context()).data
        return Response(data, status=status_code)

    @extend_schema(responses={201: PeopleSerializer})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        password = data.pop("password")
        person = create_account(request.user, User(**data), password)
        return self.person_response(person, status.HTTP_201_CREATED)

    @extend_schema(responses=PeopleSerializer)
    def partial_update(self, request, *args, **kwargs):
        person = self.get_object()
        serializer = self.get_serializer(person, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        for field, value in serializer.validated_data.items():
            setattr(person, field, value)
        return self.person_response(update_contact_details(request.user, person))

    @extend_schema(request=None, responses=PeopleSerializer)
    @action(detail=True, methods=["post"], url_path="toggle-access")
    def toggle(self, request, pk=None):
        """Deactivate an active account or reactivate an inactive one (never your own)."""
        return self.person_response(toggle_access(request.user, self.get_object()))
