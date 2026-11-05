from django.urls import path

from . import views

urlpatterns = [
    path("setup/", views.setup, name="setup"),
    path("setup/<str:kind>/new/", views.setup_create, name="setup_create"),
    path("setup/<str:kind>/<int:pk>/edit/", views.setup_edit, name="setup_edit"),
]
