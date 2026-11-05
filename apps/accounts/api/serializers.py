from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from apps.organization.api.serializers import BranchSerializer

from ..models import User


class TokenObtainSerializer(TokenObtainPairSerializer):
    """Username and password in, an access and refresh token pair out."""

    def validate(self, attrs):
        # Same normalisation as the web sign-in form: usernames are stored lower-case.
        attrs[self.username_field] = attrs[self.username_field].strip().lower()
        data = super().validate(attrs)
        data["must_change_password"] = self.user.must_change_password
        return data


class TokenPairSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()


class UserSummarySerializer(serializers.ModelSerializer):
    """Just enough to show who someone is, for nesting in other records."""

    display_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = ["id", "display_name", "role"]
        read_only_fields = fields


class PersonSerializer(serializers.ModelSerializer):
    """An account as other people see it: name, role and branch, nothing private."""

    display_name = serializers.CharField(read_only=True)
    role_label = serializers.CharField(source="get_role_display", read_only=True)
    branch = BranchSerializer(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "display_name",
            "first_name",
            "last_name",
            "email",
            "role",
            "role_label",
            "branch",
            "is_active",
        ]
        read_only_fields = fields


class MeSerializer(PersonSerializer):
    student_id = serializers.SerializerMethodField()

    class Meta(PersonSerializer.Meta):
        fields = [*PersonSerializer.Meta.fields, "must_change_password", "student_id"]
        read_only_fields = fields

    def get_student_id(self, user) -> int | None:
        profile = getattr(user, "student_profile", None) if user.is_student else None
        return profile.pk if profile else None


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, style={"input_type": "password"})
    new_password = serializers.CharField(write_only=True, style={"input_type": "password"})
