from django.urls import path

from . import views

app_name = "ledger"

urlpatterns = [
    path("me/uniq/", views.my_uniq, name="my_uniq"),
    path("me/uniq.csv", views.my_uniq_csv, name="my_uniq_csv"),
]
