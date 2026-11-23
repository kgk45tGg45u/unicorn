from django.urls import path

from . import views

app_name = "macro"

urlpatterns = [
    path("on-track/", views.on_track, name="on_track"),
    path("me/world/", views.my_world, name="my_world"),
    path("open-books/snapshots.csv", views.snapshots_csv, name="snapshots_csv"),
    path("open-books/forecast-data.csv", views.forecast_data_csv, name="forecast_data_csv"),
]
