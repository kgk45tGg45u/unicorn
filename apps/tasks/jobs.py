from apps.core.jobs import job

from . import services


@job("tasks.close_applications")
def close_applications(payload):
    """When the volunteer days are over, random confirmers choose the delegate. Safe to run twice."""
    services.close_applications()


@job("tasks.expire_mandates")
def expire_mandates(payload):
    services.expire_mandates()


@job("tasks.release_stale")
def release_stale(payload):
    """A claimed task not done in time is free again."""
    services.release_stale()
