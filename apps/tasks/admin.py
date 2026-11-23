from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin

from .models import Mandate, MandateApplication, Task


@admin.register(Mandate)
class MandateAdmin(ReadOnlyAdmin):
    list_display = ("ticket", "delegate", "status", "ends_at")


@admin.register(MandateApplication)
class MandateApplicationAdmin(ReadOnlyAdmin):
    list_display = ("ticket", "member", "created_at")


@admin.register(Task)
class TaskAdmin(ReadOnlyAdmin):
    list_display = ("title", "ticket", "status", "claimed_by")
