from django.urls import path

from . import views

urlpatterns = [
    path("exams/", views.exam_list, name="exams"),
    path("exams/new/", views.exam_create, name="exam_create"),
    path("exams/<int:pk>/", views.exam_detail, name="exam_detail"),
]
