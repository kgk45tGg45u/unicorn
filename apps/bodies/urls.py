from django.urls import path

from . import views

app_name = "bodies"

urlpatterns = [
    path("tickets/<str:number>/advice/<int:union_pk>/", views.give_advice, name="give_advice"),
]
