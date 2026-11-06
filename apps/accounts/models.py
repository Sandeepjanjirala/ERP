from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from apps.organization.models import Branch


class UserManager(DjangoUserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.update(role=self.model.Role.SUPER, branch=None, must_change_password=False)
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        SUPER = "superadmin", "Super admin"
        ADMIN = "admin", "Branch admin"
        PRINCIPAL = "principal", "Principal"
        TEACHER = "teacher", "Teacher"
        STUDENT = "student", "Student"
        PARENT = "parent", "Parent"
        ACCOUNTANT = "accountant", "Accountant"

    # Role groups for access checks; docs/PERMISSIONS.md has the full matrix.
    # Academic staff: registers, marks, results and reports.
    STAFF = (Role.SUPER, Role.ADMIN, Role.PRINCIPAL, Role.TEACHER)
    MANAGERS = (Role.SUPER, Role.ADMIN)  # manage accounts and academic setup
    LEADERS = (Role.SUPER, Role.ADMIN, Role.PRINCIPAL)  # also see people, setup, activity
    # Families see only their own records (a parent: their children's), and published results.
    FAMILY = (Role.STUDENT, Role.PARENT)
    # Everyone who may see academic records (marks, attendance, reports): not accountants.
    ACADEMIC = (*STAFF, *FAMILY)
    # Everyone who works at the school, for "staff" announcements.
    EMPLOYEES = (*STAFF, Role.ACCOUNTANT)
    # Fees: invoices and payments of the branch.
    FINANCE = (Role.SUPER, Role.ADMIN, Role.ACCOUNTANT)

    email = models.EmailField(unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT)
    branch = models.ForeignKey(
        Branch, on_delete=models.PROTECT, null=True, blank=True, related_name="users"
    )
    phone = models.CharField(
        max_length=20,
        blank=True,
        validators=[
            RegexValidator(
                r"^\+?[0-9][0-9 -]{6,18}$", "Enter a phone number, e.g. +91 98480 22338."
            )
        ],
    )
    must_change_password = models.BooleanField(default=True)
    objects = UserManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower("username"), name="username_case_insensitive"),
            models.UniqueConstraint(Lower("email"), name="email_case_insensitive"),
            models.CheckConstraint(
                condition=(
                    Q(role="superadmin", branch__isnull=True, is_superuser=True, is_staff=True)
                    | (
                        Q(
                            role__in=[
                                "admin",
                                "principal",
                                "teacher",
                                "student",
                                "parent",
                                "accountant",
                            ],
                            branch__isnull=False,
                            is_superuser=False,
                            is_staff=False,
                        )
                    )
                ),
                name="role_branch_privileges",
            ),
        ]

    def clean(self):
        super().clean()
        self.username = self.username.strip().lower()
        self.email = self.email.strip().lower()
        if self.role == self.Role.SUPER:
            if self.branch_id or not self.is_superuser or not self.is_staff:
                raise ValidationError(
                    "Super admins require system privileges and no branch assignment."
                )
        elif not self.branch_id or self.is_superuser or self.is_staff:
            raise ValidationError(
                "Branch users require a branch and cannot hold system privileges."
            )

    def save(self, *args, **kwargs):
        self.full_clean(exclude=["password"])
        return super().save(*args, **kwargs)

    @property
    def display_name(self):
        return self.get_full_name() or self.username

    @property
    def system_admin(self):
        return self.is_active and self.is_superuser and self.role == self.Role.SUPER

    @property
    def is_student(self):
        return self.role == self.Role.STUDENT

    @property
    def is_parent(self):
        return self.role == self.Role.PARENT

    @property
    def is_school_staff(self):
        """Academic staff: registers, marks, results (not accountants or families)."""
        return self.role in self.STAFF

    @property
    def is_accountant(self):
        return self.role == self.Role.ACCOUNTANT

    @property
    def is_finance(self):
        """Collects fees and issues invoices: admins and accountants."""
        return self.role in self.FINANCE

    @property
    def is_family(self):
        return self.role in self.FAMILY

    @property
    def is_manager(self):
        return self.role in self.MANAGERS

    @property
    def is_leader(self):
        return self.role in self.LEADERS


class LoginAttempt(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    count = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField()

    def __str__(self):
        return f"{self.count} attempts since {self.started_at:%Y-%m-%d %H:%M}"
