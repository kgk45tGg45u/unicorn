from django.apps import AppConfig


class TradefundConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tradefund"
    label = "tradefund"

    def ready(self):
        from apps.core.management.commands import daily

        from . import jobs, payments, purchases, services, trust  # noqa: F401

        payments.register()
        trust.register()
        purchases.register()
        for entry in (
            ("tradefund.fx", {}),
            ("tradefund.deadlines", {}),
            ("tradefund.trust_monthly", {}),
            ("tradefund.caps", {}),
            ("tradefund.purchase_lists", {}),
            ("tradefund.purchases", {}),
        ):
            if entry not in daily.DAILY_JOBS:
                daily.DAILY_JOBS.append(entry)
