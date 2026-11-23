from django.apps import AppConfig


class PrivacyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.privacy"
    label = "privacy"

    def ready(self):
        from apps.core.management.commands import daily

        from . import exporters, jobs  # noqa: F401

        exporters.register_all()
        for entry in (("privacy.cleanup", {}),):
            if entry not in daily.DAILY_JOBS:
                daily.DAILY_JOBS.append(entry)
