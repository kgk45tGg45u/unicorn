from apps.core.jobs import job

from . import assist_services


@job("members.assist_summary")
def assist_summary(payload):
    """Once a month, tell each helped member what was done for them. Safe to run twice."""
    assist_services.send_monthly_summaries()
