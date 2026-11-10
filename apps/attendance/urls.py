from django.urls import path

from . import views

urlpatterns = [
    path("attendance/", views.attendance, name="attendance"),
    path("leave/", views.leave_list, name="leave_requests"),
    path("leave/new/", views.leave_create, name="leave_create"),
    path("leave/<int:pk>/decide/", views.leave_decide, name="leave_decide"),
]
