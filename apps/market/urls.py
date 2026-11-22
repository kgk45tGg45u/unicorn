from django.urls import path

from . import views

app_name = "market"

urlpatterns = [
    path("sell/", views.sell_in_person, name="sell"),
    path("sell/<str:code>/", views.sale_page, name="sale"),
    path("pay/<str:code>/", views.pay, name="pay"),
]
