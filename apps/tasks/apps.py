from django.apps import AppConfig


class TasksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tasks"
    label = "tasks"

    def ready(self):
        from apps.core.management.commands import daily

        from . import jobs, services  # noqa: F401

        services.register()
        for entry in (
            ("tasks.close_applications", {}),
            ("tasks.expire_mandates", {}),
            ("tasks.release_stale", {}),
        ):
            if entry not in daily.DAILY_JOBS:
                daily.DAILY_JOBS.append(entry)
