from django.apps import AppConfig


class PlanConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.plan"
    label = "plan"

    def ready(self):
        from apps.core.management.commands import daily

        from . import apply, jobs  # noqa: F401

        apply.register()
        for entry in (("plan.daily", {}),):
            if entry not in daily.DAILY_JOBS:
                daily.DAILY_JOBS.append(entry)
