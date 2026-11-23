from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin

from .models import ExternalPayee, FundEntry, FxRate, Holder, PaymentRequest, TrustEvent


@admin.register(FxRate)
class FxRateAdmin(ReadOnlyAdmin):
    list_display = ("date", "currency", "per_eur")


@admin.register(Holder)
class HolderAdmin(ReadOnlyAdmin):
    list_display = ("member", "status", "currency")


@admin.register(FundEntry)
class FundEntryAdmin(ReadOnlyAdmin):
    list_display = ("seq", "holder", "kind", "amount", "currency", "created_at")


@admin.register(PaymentRequest)
class PaymentRequestAdmin(ReadOnlyAdmin):
    list_display = ("id", "payer", "amount", "currency", "status", "due_date")


@admin.register(ExternalPayee)
class ExternalPayeeAdmin(ReadOnlyAdmin):
    list_display = ("id", "country", "created_at")  # the name and the account number are not shown here


@admin.register(TrustEvent)
class TrustEventAdmin(ReadOnlyAdmin):
    list_display = ("holder", "kind", "delta", "created_at")
