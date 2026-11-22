from django.urls import path

from . import views

app_name = "ledger"

urlpatterns = [
    path("open-books/", views.open_books, name="open_books"),
    path("open-books/periods.csv", views.open_books_csv, name="open_books_csv"),
    path("me/uniq/", views.my_uniq, name="my_uniq"),
    path("me/retirement/", views.retirement, name="retirement"),
    path("me/uniq.csv", views.my_uniq_csv, name="my_uniq_csv"),
]
