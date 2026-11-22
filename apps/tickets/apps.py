from django.apps import AppConfig


class TicketsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tickets"
    label = "tickets"

    def ready(self):
        from apps.core.management.commands import daily
        from apps.units import services as unit_services

        from . import actions, flags, hooks, jobs, mediation, services  # noqa: F401

        if hooks.decision_opened not in unit_services.DECISION_OPENED_HOOKS:
            unit_services.DECISION_OPENED_HOOKS.append(hooks.decision_opened)
            unit_services.DECISION_CLOSED_HOOKS.append(hooks.decision_closed)

        for entry in (("tickets.seat_deadlines", {}), ("tickets.one_person_checks", {})):
            if entry not in daily.DAILY_JOBS:
                daily.DAILY_JOBS.append(entry)
