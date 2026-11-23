from django.urls import path

from . import views

app_name = "plan"

urlpatterns = [
    path("plan/", views.home, name="home"),
    path("plan/propose/", views.propose, name="propose"),
    path("plan/group/<int:pk>/", views.group_page, name="group"),
    path("plan/variant/<int:pk>/", views.variant_page, name="variant"),
    path("plan/variant/<int:pk>/compare/<int:other>/", views.compare_page, name="compare"),
]
