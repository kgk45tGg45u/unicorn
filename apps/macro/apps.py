from django.apps import AppConfig


class MacroConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.macro"
    label = "macro"

    def ready(self):
        from apps.core.management.commands import daily

        from . import jobs, transfers  # noqa: F401

        transfers.register()

        for entry in (
            ("macro.close_period", {}),
            ("macro.pay_pensions", {}),
            ("macro.retirement_payouts", {}),
            ("macro.shred_evidence", {}),
            ("macro.lights", {}),
        ):
            if entry not in daily.DAILY_JOBS:
                daily.DAILY_JOBS.append(entry)
