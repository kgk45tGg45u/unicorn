from django.apps import AppConfig


class BodiesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.bodies"
    label = "bodies"

    def ready(self):
        from apps.core.management.commands import daily
        from apps.tickets import routing

        from . import duties, experts, jobs, local, services  # noqa: F401

        services.register()
        duties.register()
        experts.register()
        local.register()
        if duties.ask_for_advice not in routing.ROUTE_HOOKS:
            routing.ROUTE_HOOKS.append(duties.ask_for_advice)
        for entry in (("bodies.daily", {}),):
            if entry not in daily.DAILY_JOBS:
                daily.DAILY_JOBS.append(entry)
