from apps.core.jobs import job

from . import services


@job("market.write_offs")
def write_offs(payload):
    """Daily. Safe to run twice: a written-off lot is not written off again."""
    services.write_off_lots()


@job("market.auto_confirm")
def auto_confirm(payload):
    """Daily. Safe to run twice: a delivered line is not delivered again."""
    services.auto_confirm_deliveries()


@job("market.auto_confirm_line")
def auto_confirm_line(payload):
    """Queued at hand-over to run when the time to answer is over. Does nothing if it ran too early."""
    services.auto_confirm_deliveries()


@job("market.auto_confirm_bookings")
def auto_confirm_bookings(payload):
    """Daily. Safe to run twice: a confirmed booking is not confirmed again."""
    services.auto_confirm_bookings()


@job("market.auto_confirm_booking")
def auto_confirm_booking(payload):
    """Queued when a session is marked performed; does nothing if it ran too early."""
    services.auto_confirm_bookings()
