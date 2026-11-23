from django.apps import AppConfig


class MembersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.members"
    label = "members"

    def ready(self):
        from apps.core.management.commands import daily

        from . import assist, jobs, signals  # noqa: F401

        assist.connect_stamps()
        for entry in (("members.assist_summary", {}),):
            if entry not in daily.DAILY_JOBS:
                daily.DAILY_JOBS.append(entry)
