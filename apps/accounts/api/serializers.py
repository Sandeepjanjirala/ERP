from rest_framework import serializers
from rest_framework.validators import UniqueValidator
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from apps.core.api.fields import ScopedPrimaryKeyField
from apps.organization.api.serializers import BranchSerializer
from apps.organization.selectors import branches

from ..models import User
from ..policies import can_change_access, can_manage_account, staff_roles_for


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


class PeopleSerializer(PersonSerializer):
    """A row on People & access, with the actions the caller may take (from the policies)."""

    can_edit = serializers.SerializerMethodField()
    can_toggle_access = serializers.SerializerMethodField()

    class Meta(PersonSerializer.Meta):
        fields = [*PersonSerializer.Meta.fields, "can_edit", "can_toggle_access"]
        read_only_fields = fields

    def get_can_edit(self, person) -> bool:
        return can_manage_account(self.context["request"].user, person)

    def get_can_toggle_access(self, person) -> bool:
        return can_change_access(self.context["request"].user, person)


def unique_ignoring_case(label):
    # The database has the same rule (a unique index on lower(...)); this gives a field error.
    return UniqueValidator(
        queryset=User.objects.all(), lookup="iexact", message=f"This {label} is already in use."
    )


class AccountCreateFields(serializers.ModelSerializer):
    """Login details shared by staff accounts and student admissions."""

    username = serializers.CharField(max_length=150, validators=[unique_ignoring_case("username")])
    email = serializers.EmailField(validators=[unique_ignoring_case("email")])
    first_name = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "email", "password"]


class StaffAccountCreateSerializer(AccountCreateFields):
    """A new staff account. Super admins: admin, principal or teacher; branch admins: teachers."""

    role = serializers.ChoiceField(choices=User.Role.choices)
    branch = ScopedPrimaryKeyField(branches, required=False)

    class Meta(AccountCreateFields.Meta):
        fields = [*AccountCreateFields.Meta.fields, "role", "branch"]

    def validate_role(self, role):
        if role not in staff_roles_for(self.context["request"].user):
            raise serializers.ValidationError("You can't create accounts with this role.")
        return role

    def validate(self, data):
        actor = self.context["request"].user
        # Branch admins always create in their own branch; super admins must choose one.
        data.setdefault("branch", actor.branch)
        if data["branch"] is None:
            raise serializers.ValidationError({"branch": "Choose a branch."})
        return data


class ContactDetailsSerializer(serializers.ModelSerializer):
    """Only name and email can change here: never role, branch or username."""

    email = serializers.EmailField()

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]

    def validate_email(self, value):
        taken = User.objects.filter(email__iexact=value).exclude(pk=self.instance.pk)
        if taken.exists():
            raise serializers.ValidationError("This email is already in use.")
        return value


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, style={"input_type": "password"})
    new_password = serializers.CharField(write_only=True, style={"input_type": "password"})
