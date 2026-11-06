from django.urls import path

from . import views

urlpatterns = [
    path("fees/", views.invoice_list, name="fees"),
]
