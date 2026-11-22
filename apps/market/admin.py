from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin

from .models import Order, OrderLine


@admin.register(Order)
class OrderAdmin(ReadOnlyAdmin):
    list_display = ("id", "buyer", "kind", "delivery_mode", "created_at")


@admin.register(OrderLine)
class OrderLineAdmin(ReadOnlyAdmin):
    list_display = ("id", "order", "offer", "quantity", "total_uniq", "status")
