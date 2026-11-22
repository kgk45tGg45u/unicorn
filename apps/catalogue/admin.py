from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin

from .models import (
    Item,
    Offer,
    OfferInput,
    OfferTool,
    OfferValueHistory,
    OwnFreeConfirmation,
    UnitOfMeasure,
    ValueRun,
)


@admin.register(UnitOfMeasure)
class UnitOfMeasureAdmin(ReadOnlyAdmin):
    list_display = ("code", "name", "dimension")


@admin.register(Item)
class ItemAdmin(ReadOnlyAdmin):
    list_display = ("name", "kind", "uom", "status")


@admin.register(Offer)
class OfferAdmin(ReadOnlyAdmin):
    list_display = ("item", "unit", "status", "value_total")


@admin.register(OfferInput)
class OfferInputAdmin(ReadOnlyAdmin):
    list_display = ("offer", "item", "quantity_per_batch", "source")


@admin.register(OfferTool)
class OfferToolAdmin(ReadOnlyAdmin):
    list_display = ("offer", "tool_item", "source")


@admin.register(OwnFreeConfirmation)
class OwnFreeConfirmationAdmin(ReadOnlyAdmin):
    list_display = ("input", "month", "confirmed_at")


@admin.register(ValueRun)
class ValueRunAdmin(ReadOnlyAdmin):
    list_display = ("started_at", "offers", "method", "converged")


@admin.register(OfferValueHistory)
class OfferValueHistoryAdmin(ReadOnlyAdmin):
    list_display = ("run", "offer", "total")
