from django.urls import path

from . import views

app_name = "reputation"

urlpatterns = [
    path("me/recognition/<int:pk>/hide/", views.hide, name="hide"),
]
