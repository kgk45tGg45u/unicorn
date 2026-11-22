from django.apps import AppConfig


class CatalogueConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.catalogue"
    label = "catalogue"

    def ready(self):
        from apps.core.management.commands import daily

        from . import jobs  # noqa: F401

        for entry in (("catalogue.ask_own_free", {}),):
            if entry not in daily.DAILY_JOBS:
                daily.DAILY_JOBS.append(entry)
