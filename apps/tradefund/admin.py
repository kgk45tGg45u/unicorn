from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin

from .models import FundEntry, FxRate, Holder


@admin.register(FxRate)
class FxRateAdmin(ReadOnlyAdmin):
    list_display = ("date", "currency", "per_eur")


@admin.register(Holder)
class HolderAdmin(ReadOnlyAdmin):
    list_display = ("member", "status", "currency")


@admin.register(FundEntry)
class FundEntryAdmin(ReadOnlyAdmin):
    list_display = ("seq", "holder", "kind", "amount", "currency", "created_at")
