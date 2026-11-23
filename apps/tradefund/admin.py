from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin

from .models import FxRate


@admin.register(FxRate)
class FxRateAdmin(ReadOnlyAdmin):
    list_display = ("date", "currency", "per_eur")
