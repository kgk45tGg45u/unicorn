from apps.core.jobs import job

from . import close, retirement, transfers


@job("macro.close_period")
def close_period_job(payload):
    """Daily. Closes last month if it is not closed yet; safe to run twice."""
    if payload.get("period"):
        year, month = (int(x) for x in payload["period"].split("-"))
        close.close_period(year, month)
    else:
        close.close_previous_month()


@job("macro.lights")
def lights_job(payload):
    """Daily. Safe to run twice: it only refreshes the stored lights of the current month."""
    from . import lights

    lights.refresh_cache()


@job("macro.pay_pensions")
def pay_pensions(payload):
    """Daily, after the close. Safe to run twice: a pension or transfer is posted once per month."""
    transfers.pay_transfers()


@job("macro.shred_evidence")
def shred_evidence(payload):
    transfers.shred_evidence()


@job("macro.retirement_payouts")
def retirement_payouts(payload):
    """Daily. Safe to run twice: each plan pays once per month."""
    retirement.pay_plans()
