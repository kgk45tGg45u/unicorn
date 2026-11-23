from django.urls import path

from . import views

app_name = "members"

urlpatterns = [
    path("me/", views.my_account, name="my_account"),
    path("join/", views.join_about, name="join_about"),
    path("join/next/", views.join_next, name="join_next"),
    path("launch/", views.launch, name="launch"),
    path("contract/", views.contract, name="contract"),
    path("me/mediator/", views.mediator_toggle, name="mediator_toggle"),
    path("me/notify/", views.notify_toggle, name="notify_toggle"),
    path("me/suggest/", views.suggest_toggle, name="suggest_toggle"),
    path("files/<int:pk>/", views.private_file, name="private_file"),
    path("vouch/", views.vouch_page, name="vouch"),
    path("identity-checks/", views.identity_check_page, name="identity_check"),
    path("portfolio/", views.portfolio, name="portfolio"),
    path("leave/", views.leave_page, name="leave"),
    path("delete-account/", views.delete_page, name="delete"),
    path("m/<str:number>/", views.public_profile, name="public_profile"),
]
