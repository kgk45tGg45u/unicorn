from django.apps import AppConfig


class OutsideConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.outside"
    label = "outside"

    def ready(self):
        from apps.core.management.commands import daily

        from . import jobs, statement, units_link  # noqa: F401

        statement.register()
        units_link.register()
        for entry in (("outside.cancel_unpaid", {}), ("outside.wipe_contacts", {}), ("outside.confirm_deliveries", {})):
            if entry not in daily.DAILY_JOBS:
                daily.DAILY_JOBS.append(entry)
