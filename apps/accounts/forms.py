from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from apps.organization.selectors import branches

from .models import User


class LoginForm(AuthenticationForm):
    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()


class AccountForm(forms.ModelForm):
    """A new staff account. Branch admins may only create teachers, and only in their branch."""

    password = forms.CharField(
        widget=forms.PasswordInput,
        help_text="At least 12 characters. Share privately; the user must change this on first login.",
    )

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "role", "branch"]

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        self.fields["branch"].queryset = branches(actor)
        self.fields["branch"].required = True
        self.fields["first_name"].required = True
        self.fields["role"].choices = self.role_choices()
        if not actor.system_admin:
            self.fields["branch"].initial = actor.branch_id

    def role_choices(self):
        if self.actor.system_admin:
            return [("admin", "Branch admin"), ("principal", "Principal"), ("teacher", "Teacher")]
        return [("teacher", "Teacher")]

    def clean_username(self):
        value = self.cleaned_data["username"].strip().lower()
        if User.objects.filter(username__iexact=value).exists():
            raise ValidationError("This username is already in use.")
        return value

    def clean_email(self):
        value = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise ValidationError("This email is already in use.")
        return value

    def clean(self):
        data = super().clean()
        temp = User(
            username=data.get("username", ""),
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name", ""),
            email=data.get("email", ""),
        )
        if data.get("password"):
            validate_password(data["password"], user=temp)
        return data


class AccountEditForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]

    def clean_email(self):
        value = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=value).exclude(pk=self.instance.pk).exists():
            raise ValidationError("This email is already in use.")
        return value
