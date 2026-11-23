from django.contrib import admin

from .models import AuditEvent, Job, RestoreTest


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


@admin.register(RestoreTest)
class RestoreTestAdmin(ReadOnlyAdmin):
    list_display = ("ran_at", "backup_date", "ok", "operator_number")


@admin.register(Job)
class JobAdmin(ReadOnlyAdmin):
    list_display = ("kind", "status", "run_after", "attempts")


def lock_admin():
    """Make every registered model read-only, including those of other packages (CLAUDE.md section 7).

    Members change data through the app and its tickets, never through the admin.
    """
    for model_admin in admin.site._registry.values():
        if not isinstance(model_admin, ReadOnlyAdmin):
            model_admin.has_add_permission = lambda request, *args, **kwargs: False
            model_admin.has_change_permission = lambda request, *args, **kwargs: False
            model_admin.has_delete_permission = lambda request, *args, **kwargs: False
