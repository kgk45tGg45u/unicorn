from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin

from .models import Item, Offer, UnitOfMeasure


@admin.register(UnitOfMeasure)
class UnitOfMeasureAdmin(ReadOnlyAdmin):
    list_display = ("code", "name", "dimension")


@admin.register(Item)
class ItemAdmin(ReadOnlyAdmin):
    list_display = ("name", "kind", "uom", "status")


@admin.register(Offer)
class OfferAdmin(ReadOnlyAdmin):
    list_display = ("item", "unit", "status", "value_total")
