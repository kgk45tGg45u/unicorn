from django.urls import path

from . import views

app_name = "catalogue"

urlpatterns = [
    path("units/<slug:slug>/offers/new/", views.offer_new, name="offer_new"),
    path("offers/<int:pk>/recipe/", views.recipe_editor, name="recipe"),
    path("offers/<int:pk>/recipe/input/", views.recipe_add_input, name="add_input"),
    path("offers/<int:pk>/recipe/tool/", views.recipe_add_tool, name="add_tool"),
    path("offers/<int:pk>/recipe/<str:kind>/<int:row_pk>/remove/", views.recipe_remove, name="remove_row"),
    path("offers/<int:pk>/recipe/publish/", views.recipe_publish, name="publish"),
    path("inputs/<int:pk>/confirm/", views.confirm_free, name="confirm_free"),
    path("items/search/", views.item_search, name="item_search"),
    path("items/<int:pk>/", views.item_page, name="item"),
]
