from django.urls import path

from . import views

app_name = "catalogue"

urlpatterns = [
    path("items/search/", views.item_search, name="item_search"),
    path("items/<int:pk>/", views.item_page, name="item"),
]
