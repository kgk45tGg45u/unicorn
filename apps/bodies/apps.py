from django.apps import AppConfig


class BodiesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.bodies"
    label = "bodies"

    def ready(self):
        from apps.core.management.commands import daily

        from . import jobs, services  # noqa: F401

        services.register()
        for entry in (("bodies.daily", {}),):
            if entry not in daily.DAILY_JOBS:
                daily.DAILY_JOBS.append(entry)
