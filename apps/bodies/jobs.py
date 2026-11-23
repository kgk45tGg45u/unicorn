"""The daily job of the bodies: unions that stayed too small are dissolved, delegates rotate. Safe to run twice."""

from apps.core.jobs import job

from . import consumers, local, services


@job("bodies.daily")
def daily(payload):
    services.dissolve_forming()
    services.rotate_delegates()
    services.close_due_decisions()
    local.rotate_local()
    consumers.close_due_guidelines()
