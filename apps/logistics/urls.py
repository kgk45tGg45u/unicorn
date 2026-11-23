from django.urls import path

from . import views

app_name = "logistics"

urlpatterns = [
    path("pickup-points/", views.pickup_points, name="pickup_points"),
]
