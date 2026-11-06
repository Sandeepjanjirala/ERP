import django_filters
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import User
from apps.core.api.permissions import IsSignedIn, role_in

from ..models import Announcement, Notification
from ..selectors import announcements, notifications, unread_count
from ..services import mark_read, publish_announcement
from .serializers import (
    AnnouncementCreateSerializer,
    AnnouncementSerializer,
    NotificationSerializer,
    UnreadCountSerializer,
)


class AnnouncementViewSet(mixins.CreateModelMixin, viewsets.ReadOnlyModelViewSet):
    """Announcements for you, newest first. Staff post them; delivery happens in the background."""

    queryset = Announcement.objects.none()  # for the schema; get_queryset() is the real scope
    search_fields = ["title", "body"]

    def get_queryset(self):
        return announcements(self.request.user)

    def get_permissions(self):
        return [role_in(*User.STAFF)()] if self.action == "create" else [IsSignedIn()]

    def get_serializer_class(self):
        return AnnouncementCreateSerializer if self.action == "create" else AnnouncementSerializer

    @extend_schema(responses={201: AnnouncementSerializer})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        if "branch" not in data and not request.user.system_admin:
            data["branch"] = request.user.branch
        announcement = publish_announcement(request.user, Announcement(**data))
        body = AnnouncementSerializer(self.get_queryset().get(pk=announcement.pk)).data
        return Response(body, status=status.HTTP_201_CREATED)


class NotificationFilter(django_filters.FilterSet):
    unread = django_filters.BooleanFilter(field_name="read_at", lookup_expr="isnull")

    class Meta:
        model = Notification
        fields = ["unread", "kind"]


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """Your notifications, newest first. `?unread=true` for the unread ones."""

    queryset = Notification.objects.none()  # for the schema; get_queryset() is the real scope
    serializer_class = NotificationSerializer
    filterset_class = NotificationFilter

    def get_queryset(self):
        return notifications(self.request.user)

    @extend_schema(responses=UnreadCountSerializer)
    @action(detail=False, url_path="unread-count")
    def unread_count(self, request):
        """The number on the bell."""
        return Response({"unread": unread_count(request.user)})

    @extend_schema(request=None, responses=NotificationSerializer)
    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        notification = self.get_object()
        mark_read(request.user, notification)
        notification.refresh_from_db()
        return Response(NotificationSerializer(notification).data)

    @extend_schema(request=None, responses=UnreadCountSerializer)
    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request):
        mark_read(request.user)
        return Response({"unread": 0})
