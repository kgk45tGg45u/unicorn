from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    label = "core"

    def ready(self):
        from .management.commands import daily

        for entry in (("core.restore_check", {}), ("core.disk_check", {})):
            if entry not in daily.DAILY_JOBS:
                daily.DAILY_JOBS.append(entry)
