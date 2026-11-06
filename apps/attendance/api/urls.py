from django.urls import path

from . import views

urlpatterns = [
    path("classrooms/<int:pk>/register/", views.RegisterView.as_view(), name="api-register"),
]
