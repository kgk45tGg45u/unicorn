from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    label = "core"

    def ready(self):
        from .management.commands import daily

        entry = ("core.restore_check", {})
        if entry not in daily.DAILY_JOBS:
            daily.DAILY_JOBS.append(entry)
