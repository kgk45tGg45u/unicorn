from django.apps import AppConfig


class LedgerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ledger"
    label = "ledger"

    def ready(self):
        from apps.members import services as member_services

        from . import services

        if services.open_member_accounts not in member_services.VERIFIED_HOOKS:
            member_services.VERIFIED_HOOKS.append(services.open_member_accounts)
