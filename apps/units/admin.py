from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin

from .models import Unit


@admin.register(Unit)
class UnitAdmin(ReadOnlyAdmin):
    list_display = ("name", "kind", "status")
