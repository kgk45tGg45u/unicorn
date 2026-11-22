from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin

from .models import Member


@admin.register(Member)
class MemberAdmin(ReadOnlyAdmin):
    list_display = ("number", "display_name", "status")
    search_fields = ("number",)
