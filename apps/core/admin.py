from django.contrib import admin

from .models import AuditEvent


class ReadOnlyAdmin(admin.ModelAdmin):
    """Members change data through the app, never through the admin."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditEvent)
class AuditEventAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "actor_ref", "verb", "object_type", "object_id")
