from django.urls import path

from . import assist_views, views

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
    path("me/done-for-me/", assist_views.done_for_me, name="done_for_me"),
    path("assist/", assist_views.home, name="assist"),
    path("assist/start/", assist_views.start, name="assist_start"),
    path("assist/<int:pk>/sign/", assist_views.sign, name="assist_sign"),
    path("assist/<int:pk>/paper/", assist_views.paper, name="assist_paper"),
    path("assist/<int:pk>/witness/", assist_views.witness, name="assist_witness"),
    path("assist/<int:pk>/revoke/", assist_views.revoke, name="assist_revoke"),
    path("assist/<int:pk>/act/", assist_views.act, name="assist_act"),
    path("assist/stop/", assist_views.stop, name="assist_stop"),
    path("files/<int:pk>/", views.private_file, name="private_file"),
    path("vouch/", views.vouch_page, name="vouch"),
    path("identity-checks/", views.identity_check_page, name="identity_check"),
    path("portfolio/", views.portfolio, name="portfolio"),
    path("leave/", views.leave_page, name="leave"),
    path("delete-account/", views.delete_page, name="delete"),
    path("m/<str:number>/", views.public_profile, name="public_profile"),
]
