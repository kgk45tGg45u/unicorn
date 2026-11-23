from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin

from .models import ActiveMonth, Forecast, MacroSnapshot, TransferPlan


@admin.register(MacroSnapshot)
class MacroSnapshotAdmin(ReadOnlyAdmin):
    list_display = ("period", "hours_paid", "tax_rate_used", "tax_rate_next", "hours_residual")


@admin.register(ActiveMonth)
class ActiveMonthAdmin(ReadOnlyAdmin):
    list_display = ("member", "month", "kind")


@admin.register(TransferPlan)
class TransferPlanAdmin(ReadOnlyAdmin):
    list_display = ("member", "monthly_amount", "from_month", "to_month")


@admin.register(Forecast)
class ForecastAdmin(ReadOnlyAdmin):
    list_display = ("ticket", "author", "created_at")
