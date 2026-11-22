from django.urls import path

from . import views

app_name = "catalogue"

urlpatterns = [
    path("units/<slug:slug>/join-forces/", views.join_forces, name="join_forces"),
    path("open-books/io-table/", views.io_table, name="io_table"),
    path("open-books/io-table/offers.csv", views.io_offers_csv, name="io_offers_csv"),
    path("open-books/io-table/inputs.csv", views.io_inputs_csv, name="io_inputs_csv"),
    path("open-books/io-table/tools.csv", views.io_tools_csv, name="io_tools_csv"),
    path("units/<slug:slug>/offers/new/", views.offer_new, name="offer_new"),
    path("offers/<int:pk>/", views.offer_page, name="offer"),
    path("offers/<int:pk>/recipe/", views.recipe_editor, name="recipe"),
    path("offers/<int:pk>/recipe/input/", views.recipe_add_input, name="add_input"),
    path("offers/<int:pk>/recipe/tool/", views.recipe_add_tool, name="add_tool"),
    path("offers/<int:pk>/recipe/<str:kind>/<int:row_pk>/remove/", views.recipe_remove, name="remove_row"),
    path("offers/<int:pk>/recipe/publish/", views.recipe_publish, name="publish"),
    path("inputs/<int:pk>/switch/", views.switch_input, name="switch_input"),
    path("inputs/<int:pk>/confirm/", views.confirm_free, name="confirm_free"),
    path("items/search/", views.item_search, name="item_search"),
    path("items/<int:pk>/", views.item_page, name="item"),
]
