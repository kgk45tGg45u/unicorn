from apps.core.jobs import job

from . import allocation, benefits, fx, payments, purchases, trust


@job("tradefund.fx")
def fx_job(payload):
    """Daily. Safe to run twice: a day's rates are stored once."""
    fx.fetch_and_store()


@job("tradefund.deadlines")
def deadlines(payload):
    """Daily. Safe to run twice: a request that became overdue or missed is not changed again."""
    payments.run_deadlines()


@job("tradefund.trust_monthly")
def trust_monthly(payload):
    """Monthly (queued daily): the last full month. Safe to run twice: one `monthly` event per holder and month."""
    from datetime import date

    month = date.fromisoformat(payload["month"] + "-01") if payload.get("month") else None
    trust.run_monthly(month)


@job("tradefund.caps")
def caps(payload):
    """Daily. A holder above their cap is asked to pass the excess on; one open request at a time."""
    trust.move_excess()


@job("tradefund.purchase_lists")
def purchase_lists(payload):
    """Daily. Safe to run twice: a need that became a request is not turned into another."""
    purchases.purchase_lists()


@job("tradefund.purchases")
def purchases_waiting(payload):
    """Daily. Retries purchases waiting for euros and picks buyers whose time is up."""
    purchases.run_waiting()


@job("tradefund.allocate")
def allocate(payload):
    """Daily (the order of priorities is monthly). Safe to run twice: it only acts on what still waits."""
    allocation.allocate()


@job("tradefund.benefits")
def benefits_monthly(payload):
    """Daily. Safe to run twice: a claim paid for the month is not paid again."""
    benefits.run_monthly()
