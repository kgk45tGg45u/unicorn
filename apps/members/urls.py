from django.urls import path

from . import views

app_name = "members"

urlpatterns = [
    path("me/", views.my_account, name="my_account"),
    path("contract/", views.contract, name="contract"),
    path("m/<str:number>/", views.public_profile, name="public_profile"),
]
