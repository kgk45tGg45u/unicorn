from django.urls import path

from . import views

app_name = "market"

urlpatterns = [
    path("sell/", views.sell_in_person, name="sell"),
    path("sell/<str:code>/", views.sale_page, name="sale"),
    path("pay/<str:code>/", views.pay, name="pay"),
    path("reviews/line/<int:pk>/", views.review_line, name="review_line"),
    path("reviews/booking/<int:pk>/", views.review_booking, name="review_booking"),
    path("units/<slug:slug>/reviews/", views.unit_reviews, name="unit_reviews"),
]
