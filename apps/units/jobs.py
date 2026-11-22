from apps.core.jobs import job

from . import services


@job("units.close_decisions")
def close_decisions(payload):
    """Tally council decisions whose time has passed. Safe to run twice."""
    services.close_due_decisions()
