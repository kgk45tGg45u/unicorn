from apps.core.jobs import job

from . import services


@job("units.close_decisions")
def close_decisions(payload):
    """Tally council decisions whose time has passed. Safe to run twice."""
    services.close_due_decisions()


@job("units.rotate")
def rotate(payload):
    """Pass the responsibility on where its turn is over. Safe to run twice."""
    services.rotate_due()


@job("units.end_trials")
def end_trials(payload):
    services.end_trials()


@job("units.dormant")
def dormant(payload):
    services.mark_dormant()
