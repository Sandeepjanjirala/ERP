from django.urls import path

from . import views

urlpatterns = [
    path("demo/login/<slug:role>/", views.demo_login, name="demo_login"),
]
