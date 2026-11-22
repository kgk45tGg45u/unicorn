from django.urls import path

from . import views

app_name = "units"

urlpatterns = [
    path("", views.unit_list, name="list"),
    path("me/hours/", views.my_hours, name="my_hours"),
    path("me/hours/timer/", views.timer, name="timer"),
    path("me/hours/<int:pk>/submit/", views.submit_draft, name="submit_draft"),
    path("open/", views.open_unit, name="open"),
    path("requests/<int:pk>/decide/", views.decide_join, name="decide_join"),
    path("decisions/<int:pk>/", views.decision_page, name="decision"),
    path("decisions/<int:pk>/vote/", views.decision_vote, name="decision_vote"),
    path("<slug:slug>/decisions/", views.decision_list, name="decisions"),
    path("<slug:slug>/", views.unit_page, name="unit"),
    path("<slug:slug>/join/", views.request_join, name="join"),
    path("<slug:slug>/rules/", views.rules_page, name="rules"),
    path("<slug:slug>/rules/sign/", views.sign_rules, name="sign_rules"),
    path("<slug:slug>/decline-turn/", views.decline_turn, name="decline_turn"),
    path("<slug:slug>/reopen/", views.reopen, name="reopen"),
    path("<slug:slug>/approve/", views.approve_page, name="approve"),
    path("<slug:slug>/hours/", views.unit_hours, name="unit_hours"),
    path("<slug:slug>/leave/", views.leave, name="leave"),
]
