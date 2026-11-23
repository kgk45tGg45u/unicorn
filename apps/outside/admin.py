from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin

from .models import Invoice, OutsideCustomer, SellerProfile


@admin.register(SellerProfile)
class SellerProfileAdmin(ReadOnlyAdmin):
    list_display = ("member", "active", "small_business")


@admin.register(OutsideCustomer)
class OutsideCustomerAdmin(ReadOnlyAdmin):
    list_display = ("id", "country", "privacy_consent_at")  # no names or addresses


@admin.register(Invoice)
class InvoiceAdmin(ReadOnlyAdmin):
    list_display = ("number", "total", "currency", "issued_on")
