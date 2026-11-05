from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("accounts/login/", views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/password/change/", views.PasswordChangeView.as_view(), name="password_change"),
    path(
        "accounts/password/changed/",
        auth_views.PasswordChangeDoneView.as_view(
            template_name="registration/auth_done.html",
            extra_context={
                "heading": "Password updated",
                "description": "Your new password is ready. Continue to your dashboard.",
            },
        ),
        name="password_change_done",
    ),
    path("accounts/password/reset/", views.PasswordResetView.as_view(), name="password_reset"),
    path(
        "accounts/password/reset/sent/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="registration/auth_done.html",
            extra_context={
                "heading": "Check your email",
                "description": "If an active account matches, a reset link will be sent. Contact your school administrator if it does not arrive.",
            },
        ),
        name="password_reset_done",
    ),
    path(
        "accounts/password/reset/<uidb64>/<token>/",
        views.PasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "accounts/password/reset/complete/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="registration/auth_done.html",
            extra_context={
                "heading": "Password reset complete",
                "description": "You can now sign in with your new password.",
            },
        ),
        name="password_reset_complete",
    ),
    path("users/", views.user_list, name="users"),
    path("users/new/", views.account_create, name="user_create"),
    path("users/<int:pk>/toggle/", views.toggle_user, name="toggle_user"),
    path("users/<int:pk>/edit/", views.user_edit, name="user_edit"),
]
