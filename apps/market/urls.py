from django.urls import path

from . import views

app_name = "market"

urlpatterns = [
    path("market/", views.market_index, name="index"),
    path("needs/", views.needs_board, name="needs"),
    path("items/<int:pk>/wait/", views.join_waiting_list, name="wait"),
    path("offers/<int:pk>/order/", views.order_offer, name="order"),
    path("slots/<int:pk>/book/", views.book_slot, name="book"),
    path("me/orders/", views.my_orders, name="my_orders"),
    path("me/orders/<str:kind>/<int:pk>/<str:action>/", views.my_order_action, name="my_order_action"),
    path("units/<slug:slug>/work/", views.unit_work, name="work"),
    path("units/<slug:slug>/work/<str:action>/", views.unit_work_action, name="work_action"),
    path("sell/", views.sell_in_person, name="sell"),
    path("sell/<str:code>/", views.sale_page, name="sale"),
    path("pay/<str:code>/", views.pay, name="pay"),
    path("reviews/line/<int:pk>/", views.review_line, name="review_line"),
    path("reviews/booking/<int:pk>/", views.review_booking, name="review_booking"),
    path("units/<slug:slug>/reviews/", views.unit_reviews, name="unit_reviews"),
]
