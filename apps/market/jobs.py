from apps.core.jobs import job

from . import services


@job("market.write_offs")
def write_offs(payload):
    """Daily. Safe to run twice: a written-off lot is not written off again."""
    services.write_off_lots()
