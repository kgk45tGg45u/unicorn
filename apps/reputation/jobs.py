from apps.core.jobs import job

from . import services


@job("reputation.recompute")
def recompute(payload):
    """Rebuild the cache of scores from the helpful marks. Safe to run twice."""
    services.recompute()
