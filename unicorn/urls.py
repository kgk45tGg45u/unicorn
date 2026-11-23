"""
URL configuration for unicorn project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from apps.core.admin import lock_admin

admin.autodiscover()
lock_admin()

urlpatterns = [
    path(f"{settings.ADMIN_PATH}/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("", include("apps.members.urls")),
    path("", include("apps.ledger.urls")),
    path("units/", include("apps.units.urls")),
    path("", include("apps.catalogue.urls")),
    path("", include("apps.market.urls")),
    path("", include("apps.tickets.urls")),
    path("", include("apps.votes.urls")),
    path("", include("apps.tasks.urls")),
    path("", include("apps.tradefund.urls")),
    path("", include("apps.macro.urls")),
    path("", include("apps.outside.urls")),
    path("", include("apps.plan.urls")),
    path("", include("apps.logistics.urls")),
    path("", include("apps.bodies.urls")),
    path("", include("apps.reputation.urls")),
    path("", include("apps.privacy.urls")),
    path("rules/", include("apps.rules.urls")),
    path("", include("apps.core.urls")),
]

handler500 = "apps.core.views.server_error"
