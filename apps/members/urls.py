from django.urls import path

from . import views

app_name = "members"

urlpatterns = [
    path("me/", views.my_account, name="my_account"),
    path("join/", views.join_about, name="join_about"),
    path("join/next/", views.join_next, name="join_next"),
    path("launch/", views.launch, name="launch"),
    path("contract/", views.contract, name="contract"),
    path("files/<int:pk>/", views.private_file, name="private_file"),
    path("vouch/", views.vouch_page, name="vouch"),
    path("identity-checks/", views.identity_check_page, name="identity_check"),
    path("m/<str:number>/", views.public_profile, name="public_profile"),
]
