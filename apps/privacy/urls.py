from django.urls import path

from . import views

app_name = "privacy"

urlpatterns = [
    path("me/data/export/", views.request_export, name="request_export"),
    path("me/data/<int:pk>/", views.data_page, name="data"),
    path("me/data/<int:pk>/download/", views.download, name="download"),
]
