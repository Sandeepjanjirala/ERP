from django.urls import path

from . import views

urlpatterns = [
    path("setup/", views.setup, name="setup"),
    path("setup/<str:kind>/new/", views.setup_create, name="setup_create"),
    path("setup/<str:kind>/<int:pk>/edit/", views.setup_edit, name="setup_edit"),
    path("setup/years/<int:pk>/terms/", views.year_terms, name="year_terms"),
    path("timetable/", views.timetable_index, name="timetable"),
    path("timetable/mine/", views.my_timetable, name="my_timetable"),
    path("timetable/<int:pk>/", views.classroom_timetable, name="classroom_timetable"),
    path("timetable/<int:pk>/cell/", views.timetable_cell, name="timetable_cell"),
]
