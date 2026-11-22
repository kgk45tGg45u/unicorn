from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin

from .models import JoinRequest, Unit, UnitMembership


@admin.register(Unit)
class UnitAdmin(ReadOnlyAdmin):
    list_display = ("name", "kind", "status")


@admin.register(UnitMembership)
class UnitMembershipAdmin(ReadOnlyAdmin):
    list_display = ("unit", "member", "is_council", "joined_at", "left_at")


@admin.register(JoinRequest)
class JoinRequestAdmin(ReadOnlyAdmin):
    list_display = ("unit", "member", "status")
