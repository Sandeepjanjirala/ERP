from rest_framework import serializers

from apps.academics.api.serializers import ClassroomSummarySerializer
from apps.academics.selectors import classrooms
from apps.accounts.api.serializers import UserSummarySerializer
from apps.core.api.fields import ScopedPrimaryKeyField
from apps.organization.selectors import branches

from ..models import Announcement, Notification


class AnnouncementSerializer(serializers.ModelSerializer):
    author = UserSummarySerializer(read_only=True)
    classroom = ClassroomSummarySerializer(read_only=True)
    audience_label = serializers.CharField(source="get_audience_display", read_only=True)

    class Meta:
        model = Announcement
        fields = [
            "id",
            "title",
            "body",
            "audience",
            "audience_label",
            "branch",
            "classroom",
            "author",
            "created_at",
        ]
        read_only_fields = fields


class AnnouncementCreateSerializer(serializers.ModelSerializer):
    """Leaders announce to their branch; teachers to a class they teach. Leave `branch` out to
    use your own; only super admins may send to every branch (branch null)."""

    branch = ScopedPrimaryKeyField(branches, required=False, allow_null=True)
    classroom = ScopedPrimaryKeyField(classrooms, required=False, allow_null=True)

    class Meta:
        model = Announcement
        fields = ["branch", "audience", "classroom", "title", "body"]
        validators = []


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "kind", "title", "body", "url", "created_at", "read_at"]
        read_only_fields = fields


class UnreadCountSerializer(serializers.Serializer):
    unread = serializers.IntegerField()
