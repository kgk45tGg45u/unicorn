"""The daily job of the bodies: unions that stayed too small are dissolved, delegates rotate. Safe to run twice."""

from apps.core.jobs import job

from . import services


@job("bodies.daily")
def daily(payload):
    services.dissolve_forming()
