from django.urls import path

from . import views

app_name = "units"

urlpatterns = [
    path("", views.unit_list, name="list"),
    path("requests/<int:pk>/decide/", views.decide_join, name="decide_join"),
    path("<slug:slug>/", views.unit_page, name="unit"),
    path("<slug:slug>/join/", views.request_join, name="join"),
    path("<slug:slug>/rules/", views.rules_page, name="rules"),
    path("<slug:slug>/rules/sign/", views.sign_rules, name="sign_rules"),
    path("<slug:slug>/leave/", views.leave, name="leave"),
]
