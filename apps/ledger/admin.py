from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin

from .models import Account, AccountBalance, ChainHead, Entry, Hold, Period, Transaction


@admin.register(Account)
class AccountAdmin(ReadOnlyAdmin):
    list_display = ("kind", "member")


@admin.register(AccountBalance)
class AccountBalanceAdmin(ReadOnlyAdmin):
    list_display = ("account", "balance")


@admin.register(Period)
class PeriodAdmin(ReadOnlyAdmin):
    list_display = ("year", "month", "status", "tax_rate")


@admin.register(Transaction)
class TransactionAdmin(ReadOnlyAdmin):
    list_display = ("seq", "kind", "reason", "created_at")


@admin.register(Entry)
class EntryAdmin(ReadOnlyAdmin):
    list_display = ("transaction", "account", "amount")


@admin.register(ChainHead)
class ChainHeadAdmin(ReadOnlyAdmin):
    list_display = ("name", "last_seq", "last_hash")


@admin.register(Hold)
class HoldAdmin(ReadOnlyAdmin):
    list_display = ("account", "amount", "status")
