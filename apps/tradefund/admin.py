from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin

from .models import (
    BuyerVolunteer,
    ExternalPayee,
    FundEntry,
    FxRate,
    GroupTool,
    Holder,
    PaymentRequest,
    PurchaseRequest,
    TrustEvent,
)


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


@admin.register(PurchaseRequest)
class PurchaseRequestAdmin(ReadOnlyAdmin):
    list_display = ("id", "description", "est_price", "currency", "status")


@admin.register(GroupTool)
class GroupToolAdmin(ReadOnlyAdmin):
    list_display = ("item", "lent_to_unit", "euro_price", "status")


@admin.register(BuyerVolunteer)
class BuyerVolunteerAdmin(ReadOnlyAdmin):
    list_display = ("purchase", "holder", "created_at")
