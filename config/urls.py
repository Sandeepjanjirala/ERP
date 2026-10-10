from django.urls import path
from django.contrib.auth import views as auth
from school import views

urlpatterns = [
    path('health/',views.health,name='health'),
    path('accounts/login/',views.LoginView.as_view(),name='login'),
    path('accounts/logout/',auth.LogoutView.as_view(),name='logout'),
    path('accounts/password/change/',views.PasswordChangeView.as_view(),name='password_change'),
    path('accounts/password/changed/',auth.PasswordChangeDoneView.as_view(template_name='registration/auth_done.html',extra_context={'heading':'Password updated','description':'Your new password is ready. Continue to your dashboard.'}),name='password_change_done'),
    path('accounts/password/reset/',views.PasswordResetView.as_view(),name='password_reset'),
    path('accounts/password/reset/sent/',auth.PasswordResetDoneView.as_view(template_name='registration/auth_done.html',extra_context={'heading':'Check your email','description':'If an active account matches, a reset link will be sent. Contact your school administrator if it does not arrive.'}),name='password_reset_done'),
    path('accounts/password/reset/<uidb64>/<token>/',views.PasswordResetConfirmView.as_view(),name='password_reset_confirm'),
    path('accounts/password/reset/complete/',auth.PasswordResetCompleteView.as_view(template_name='registration/auth_done.html',extra_context={'heading':'Password reset complete','description':'You can now sign in with your new password.'}),name='password_reset_complete'),
    path('',views.dashboard,name='dashboard'),
    path('students/',views.student_list,name='students'),
    path('students/new/',views.account_create,{'kind':'student'},name='student_create'),
    path('students/<int:pk>/report/',views.student_report,name='student_report'),
    path('users/',views.user_list,name='users'),
    path('users/new/',views.account_create,name='user_create'),
    path('users/<int:pk>/toggle/',views.toggle_user,name='toggle_user'),
    path('users/<int:pk>/edit/',views.user_edit,name='user_edit'),
    path('setup/',views.setup,name='setup'),
    path('setup/<str:kind>/new/',views.setup_create,name='setup_create'),
    path('setup/<str:kind>/<int:pk>/edit/',views.setup_edit,name='setup_edit'),
    path('attendance/',views.attendance,name='attendance'),
    path('exams/',views.exam_list,name='exams'),
    path('exams/new/',views.exam_create,name='exam_create'),
    path('exams/<int:pk>/',views.exam_detail,name='exam_detail'),
    path('reports/',views.reports,name='reports'),
    path('activity/',views.audit_log,name='audit'),
]
