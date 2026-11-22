from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin

from .models import Parameter, ParameterChange


@admin.register(Parameter)
class ParameterAdmin(ReadOnlyAdmin):
    list_display = ("key", "value", "tier")
    search_fields = ("key",)


@admin.register(ParameterChange)
class ParameterChangeAdmin(ReadOnlyAdmin):
    list_display = ("parameter", "old_value", "new_value", "decided_by", "decided_at")
