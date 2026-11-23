from django.urls import path

from . import views

app_name = "tradefund"

urlpatterns = [
    path("fund/", views.fund_public, name="public"),
    path("fund/statement/<int:year>/", views.statement_page, name="statement"),
    path("fund/statement/<int:year>/<str:fmt>/", views.statement_page, name="statement_csv"),
    path("fund/become-a-holder/", views.become_holder, name="become_holder"),
    path("fund/me/", views.my_holding, name="mine"),
    path("fund/pay/", views.pay_list, name="pay_list"),
    path("fund/pay/<int:pk>/", views.pay_detail, name="pay_detail"),
    path("fund/purchase/", views.purchase_list, name="purchase_list"),
    path("fund/purchase/new/", views.purchase_new, name="purchase_new"),
    path("fund/purchase/<int:pk>/", views.purchase_detail, name="purchase_detail"),
    path("fund/donate/", views.donate, name="donate"),
    path("fund/donations/", views.my_donations, name="my_donations"),
    path("fund/benefits/", views.benefits_page, name="benefits"),
    path("fund/trust/", views.trust_page, name="trust"),
    path("fund/trust/<int:pk>/contest/", views.trust_contest, name="trust_contest"),
]
