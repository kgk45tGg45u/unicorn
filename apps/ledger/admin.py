from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin

from .models import Account, AccountBalance, Period


@admin.register(Account)
class AccountAdmin(ReadOnlyAdmin):
    list_display = ("kind", "member")


@admin.register(AccountBalance)
class AccountBalanceAdmin(ReadOnlyAdmin):
    list_display = ("account", "balance")


@admin.register(Period)
class PeriodAdmin(ReadOnlyAdmin):
    list_display = ("year", "month", "status", "tax_rate")
