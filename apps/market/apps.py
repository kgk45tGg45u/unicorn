from django.apps import AppConfig


class MarketConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.market"
    label = "market"

    def ready(self):
        from apps.core.management.commands import daily

        from . import jobs, measure, services  # noqa: F401

        measure.register()

        for entry in (
            ("market.write_offs", {}),
            ("market.auto_confirm", {}),
            ("market.auto_confirm_bookings", {}),
            ("market.standing_orders", {}),
            ("market.expire_sales", {}),
            ("market.plausibility", {}),
        ):
            if entry not in daily.DAILY_JOBS:
                daily.DAILY_JOBS.append(entry)
