from apps.core.jobs import job

from . import services


@job("outside.cancel_unpaid")
def cancel_unpaid(payload):
    """Daily. Safe to run twice: a cancelled order is not cancelled again."""
    services.cancel_unpaid()


@job("outside.wipe_contacts")
def wipe_contacts(payload):
    """Daily. Safe to run twice: wiped contact fields stay wiped."""
    services.wipe_contacts()
