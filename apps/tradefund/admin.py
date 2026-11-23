from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin

from .models import FxRate, Holder


@admin.register(FxRate)
class FxRateAdmin(ReadOnlyAdmin):
    list_display = ("date", "currency", "per_eur")


@admin.register(Holder)
class HolderAdmin(ReadOnlyAdmin):
    list_display = ("member", "status", "currency")
