from django.urls import path

from . import views

app_name = "rules"

urlpatterns = [
    path("", views.index, name="index"),
    path("history/<str:key>/", views.history, name="history"),
]
