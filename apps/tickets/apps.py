from django.apps import AppConfig


class TicketsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tickets"
    label = "tickets"

    def ready(self):
        from apps.core.management.commands import daily

        from . import actions, jobs, services  # noqa: F401

        for entry in (("tickets.seat_deadlines", {}), ("tickets.one_person_checks", {})):
            if entry not in daily.DAILY_JOBS:
                daily.DAILY_JOBS.append(entry)
