from django.urls import path

from . import views

app_name = "tradefund"

urlpatterns = [
    path("fund/become-a-holder/", views.become_holder, name="become_holder"),
    path("fund/me/", views.my_holding, name="mine"),
    path("fund/pay/", views.pay_list, name="pay_list"),
    path("fund/pay/<int:pk>/", views.pay_detail, name="pay_detail"),
    path("fund/trust/", views.trust_page, name="trust"),
    path("fund/trust/<int:pk>/contest/", views.trust_contest, name="trust_contest"),
]
