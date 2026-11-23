from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("healthz", views.healthz, name="healthz"),
    path("offline/", views.offline, name="offline"),
    path("sw.js", views.service_worker, name="sw"),
    path(".well-known/security.txt", views.security_txt, name="security_txt"),
    path("imprint/", views.legal_page, {"name": "imprint"}, name="imprint"),
    path("privacy/", views.legal_page, {"name": "privacy"}, name="privacy"),
    path("terms/", views.legal_page, {"name": "terms"}, name="terms"),
    path("third-party/", views.legal_page, {"name": "third-party"}, name="third_party"),
]
