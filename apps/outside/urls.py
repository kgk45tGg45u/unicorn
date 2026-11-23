from django.urls import path

from . import views

app_name = "outside"

urlpatterns = [
    path("shop/", views.shop, name="shop"),
    path("shop/consumer-information/", views.consumer_info, name="consumer_info"),
    path("shop/offer/<int:pk>/", views.checkout, name="checkout"),
    path("shop/order/<str:token>/", views.order_page, name="order"),
    path("shop/order/<str:token>/withdraw/", views.withdraw, name="withdraw"),
    path("shop/order/<str:token>/received/", views.received, name="received"),
    path("shop/order/<str:token>/invoice/", views.customer_invoice, name="customer_invoice"),
    path("shop/seller/", views.seller_area, name="seller"),
    path("shop/seller/invoice/<int:pk>/", views.seller_invoice, name="seller_invoice"),
]
