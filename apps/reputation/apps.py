from django.apps import AppConfig


class ReputationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reputation"
    label = "reputation"

    def ready(self):
        from apps.core.management.commands import daily
        from apps.tickets import routing

        from . import jobs, services  # noqa: F401

        if services.suggest_for_ticket not in routing.SUGGESTERS:
            routing.SUGGESTERS.append(services.suggest_for_ticket)
        if services.notify_suggested not in routing.ROUTE_HOOKS:
            routing.ROUTE_HOOKS.append(services.notify_suggested)
        for entry in (("reputation.recompute", {}),):
            if entry not in daily.DAILY_JOBS:
                daily.DAILY_JOBS.append(entry)
