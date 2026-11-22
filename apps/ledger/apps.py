from django.apps import AppConfig


class LedgerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ledger"
    label = "ledger"

    def ready(self):
        from apps.core.management.commands import daily
        from apps.members import services as member_services

        from . import jobs, services  # noqa: F401

        if services.open_member_accounts not in member_services.VERIFIED_HOOKS:
            member_services.VERIFIED_HOOKS.append(services.open_member_accounts)

        for entry in (("ledger.audit", {}), ("ledger.fingerprint", {})):
            if entry not in daily.DAILY_JOBS:
                daily.DAILY_JOBS.append(entry)
