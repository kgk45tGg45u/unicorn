from django.apps import AppConfig


class TradefundConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tradefund"
    label = "tradefund"

    def ready(self):
        from apps.core.management.commands import daily

        from . import jobs  # noqa: F401

        for entry in (("tradefund.fx", {}),):
            if entry not in daily.DAILY_JOBS:
                daily.DAILY_JOBS.append(entry)
