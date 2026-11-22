from apps.core.jobs import job

from . import measure, services


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


@job("market.standing_orders")
def standing_orders(payload):
    """Daily. Safe to run twice: after a run, no standing order is due today any more."""
    services.run_standing_orders()


@job("market.expire_sales")
def expire_sales(payload):
    services.expire_sales()


@job("market.plausibility")
def plausibility(payload):
    """Monthly (queued daily): checks the last full month. Safe to run twice: each offer and month has one record."""
    from datetime import date

    month = date.fromisoformat(payload["month"] + "-01") if payload.get("month") else None
    measure.run_plausibility(month)
