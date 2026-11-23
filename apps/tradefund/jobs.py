from apps.core.jobs import job

from . import fx


@job("tradefund.fx")
def fx_job(payload):
    """Daily. Safe to run twice: a day's rates are stored once."""
    fx.fetch_and_store()
