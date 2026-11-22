from django.apps import AppConfig


class UnitsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.units"
    label = "units"

    def ready(self):
        from apps.core.management.commands import daily

        from . import jobs, services  # noqa: F401

        for entry in (("units.close_decisions", {}), ("units.rotate", {})):
            if entry not in daily.DAILY_JOBS:
                daily.DAILY_JOBS.append(entry)
