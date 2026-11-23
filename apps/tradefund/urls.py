from django.urls import path

from . import views

app_name = "tradefund"

urlpatterns = [
    path("fund/become-a-holder/", views.become_holder, name="become_holder"),
    path("fund/me/", views.my_holding, name="mine"),
]
