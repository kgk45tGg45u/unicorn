from apps.core.jobs import job

from . import services


@job("catalogue.ask_own_free")
def ask_own_free(payload):
    """Monthly. Safe to run twice: one question per input and month."""
    services.ask_own_free()


@job("catalogue.recompute")
def recompute(payload):
    """Compute all labour values. Safe to run twice."""
    services.recompute_values()
