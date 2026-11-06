from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.audit.services import audit
from apps.core.exceptions import error_text
from apps.core.pagination import paginate

from .decorators import role_required
from .forms import AccountEditForm, AccountForm, LoginForm
from .models import LoginAttempt, User
from .policies import can_change_access, can_manage_account
from .selectors import branch_accounts, people
from .services import change_password, create_account, toggle_access, update_contact_details
from .throttling import throttle


class LoginView(auth_views.LoginView):
    authentication_form = LoginForm
    template_name = "registration/login.html"
    redirect_authenticated_user = True
    extra_context = {"title": "Sign in"}

    def post(self, request, *args, **kwargs):
        allowed, self.throttle_key = throttle("portal-login", request.POST.get("username", ""))
        if not allowed:
            return render(
                request,
                self.template_name,
                {
                    **self.extra_context,
                    "form": self.get_form_class()(request=request),
                    "login_error": "Too many attempts. Please wait 15 minutes before trying again.",
                },
                status=429,
            )
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        LoginAttempt.objects.filter(pk=self.throttle_key).delete()
        response = super().form_valid(form)
        audit(
            self.request.user, self.request.user.branch, "account.login", self.request.user.username
        )
        return response


class PasswordChangeView(auth_views.PasswordChangeView):
    template_name = "registration/auth_form.html"
    extra_context = {
        "heading": "Set your password",
        "description": "Choose a private password with at least 12 characters.",
    }

    def form_valid(self, form):
        change_password(
            form.user, form.cleaned_data["old_password"], form.cleaned_data["new_password1"]
        )
        # Changing the password rotates the session hash; keep this browser signed in.
        update_session_auth_hash(self.request, form.user)
        return HttpResponseRedirect(self.get_success_url())


class PasswordResetView(auth_views.PasswordResetView):
    template_name = "registration/auth_form.html"
    email_template_name = "registration/password_reset_email.txt"
    subject_template_name = "registration/password_reset_subject.txt"
    # Emails render without the request, so context processors don't run: pass the brand in.
    extra_email_context = {"brand": settings.BRAND}
    extra_context = {
        "heading": "Reset your password",
        "description": "Enter your account email. If an active account exists, you will receive a reset link.",
    }

    def post(self, request, *args, **kwargs):
        allowed, _ = throttle("portal-reset", request.POST.get("email", ""), limit=3)
        if not allowed:
            return redirect("password_reset_done")
        return super().post(request, *args, **kwargs)


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "registration/auth_form.html"
    extra_context = {
        "heading": "Choose a new password",
        "description": "Reset links expire after one hour.",
    }

    def form_valid(self, form):
        response = super().form_valid(form)
        form.user.must_change_password = False
        form.user.save(update_fields=["must_change_password"])
        audit(form.user, form.user.branch, "account.password_reset", form.user.username)
        return response


@role_required(*User.LEADERS)
def user_list(request):
    page_obj = paginate(request, people(request.user))
    # The template shows actions from the same policy the services enforce.
    for person in page_obj:
        person.can_edit = can_manage_account(request.user, person)
        person.can_toggle = can_change_access(request.user, person)
    return render(
        request, "accounts/user_list.html", {"title": "People & access", "page_obj": page_obj}
    )


@role_required(*User.MANAGERS)
def account_create(request):
    form = AccountForm(request.POST or None, actor=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            user = create_account(
                request.user, form.save(commit=False), form.cleaned_data["password"]
            )
        except (ValidationError, IntegrityError) as exc:
            form.add_error(
                None,
                error_text(
                    exc,
                    "A matching account or enrollment already exists. Please review the details.",
                ),
            )
        else:
            messages.success(
                request,
                f"{user.display_name} can now sign in. Their first login requires a password change.",
            )
            return redirect("users")
    return render(
        request,
        "form_page.html",
        {
            "title": "Create staff account",
            "form": form,
            "description": "Accounts belong to one branch. Initial passwords must be shared privately.",
        },
    )


@require_POST
@role_required(*User.MANAGERS)
def toggle_user(request, pk):
    toggle_access(request.user, get_object_or_404(branch_accounts(request.user), pk=pk))
    messages.success(request, "Account access updated.")
    return redirect("users")


@role_required(*User.MANAGERS)
def user_edit(request, pk):
    person = get_object_or_404(branch_accounts(request.user), pk=pk)
    if not can_manage_account(request.user, person):
        raise PermissionDenied
    form = AccountEditForm(request.POST or None, instance=person)
    if request.method == "POST" and form.is_valid():
        update_contact_details(request.user, form.save(commit=False))
        messages.success(request, "Account details updated. Role and branch are unchanged.")
        return redirect("users")
    return render(
        request,
        "form_page.html",
        {
            "title": f"Edit {person.display_name}",
            "form": form,
            "description": "Update contact details. Role and branch reassignment require a supervised administrator migration.",
        },
    )
