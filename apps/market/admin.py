from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin

from .models import (
    Booking,
    InputRequest,
    Order,
    OrderLine,
    ProductionOrder,
    PurchaseNeed,
    ServiceSlot,
    StandingOrder,
    StockLot,
    WasteRecord,
    WeeklyPlan,
)


@admin.register(Order)
class OrderAdmin(ReadOnlyAdmin):
    list_display = ("id", "buyer", "kind", "delivery_mode", "created_at")


@admin.register(OrderLine)
class OrderLineAdmin(ReadOnlyAdmin):
    list_display = ("id", "order", "offer", "quantity", "total_uniq", "status")


@admin.register(ProductionOrder)
class ProductionOrderAdmin(ReadOnlyAdmin):
    list_display = ("id", "offer", "quantity", "origin", "status", "due_date")


@admin.register(WeeklyPlan)
class WeeklyPlanAdmin(ReadOnlyAdmin):
    list_display = ("offer", "quantity_per_week", "valid_from")


@admin.register(InputRequest)
class InputRequestAdmin(ReadOnlyAdmin):
    list_display = ("id", "production_order", "item", "quantity", "source", "status", "due_date")


@admin.register(PurchaseNeed)
class PurchaseNeedAdmin(ReadOnlyAdmin):
    list_display = ("unit", "item", "month", "quantity", "euro_estimate", "status")


@admin.register(StockLot)
class StockLotAdmin(ReadOnlyAdmin):
    list_display = ("id", "offer", "quantity", "quantity_left", "origin", "status", "expires_at")


@admin.register(WasteRecord)
class WasteRecordAdmin(ReadOnlyAdmin):
    list_display = ("lot", "quantity", "hours", "period", "created_at")


@admin.register(ServiceSlot)
class ServiceSlotAdmin(ReadOnlyAdmin):
    list_display = ("id", "offer", "provider", "starts_at", "capacity_left", "status")


@admin.register(Booking)
class BookingAdmin(ReadOnlyAdmin):
    list_display = ("id", "slot", "customer", "price_uniq", "status")


@admin.register(StandingOrder)
class StandingOrderAdmin(ReadOnlyAdmin):
    list_display = ("member", "offer", "quantity", "every", "next_date", "status")
