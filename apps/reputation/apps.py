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
        from apps.core import hooks
        from apps.tickets import flags

        if services.on_recognition not in hooks.RECOGNITION_HANDLERS:
            hooks.RECOGNITION_HANDLERS.append(services.on_recognition)
        flags.register_target("thanks", _thanks_target())
        for entry in (("reputation.recompute", {}),):
            if entry not in daily.DAILY_JOBS:
                daily.DAILY_JOBS.append(entry)


def _thanks_target():
    """How a thank-you is reported like any content (P06.T08)."""
    from django.utils.translation import gettext as _

    from apps.tickets.flags import FlagTarget
    from apps.units import services as unit_services

    from .models import Recognition

    return FlagTarget(
        model=Recognition,
        owners=lambda obj: ([w.member for w in unit_services.workers(obj.unit)], [obj.unit_id]),
        describe=lambda: _("a thank-you"),
        excerpt=lambda obj: f'"{obj.text[:300]}"',
    )
