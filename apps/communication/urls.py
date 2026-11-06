from django.urls import path

from . import views

urlpatterns = [
    path("announcements/", views.announcement_list, name="announcements"),
    path("announcements/new/", views.announcement_create, name="announcement_create"),
    path("notifications/", views.notification_list, name="notifications"),
    path("notifications/<int:pk>/open/", views.notification_open, name="notification_open"),
]
