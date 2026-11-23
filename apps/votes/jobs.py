from apps.core.jobs import job

from . import elections, services


@job("votes.close_petitions")
def close_petitions(payload):
    """Petitions past their time fail. Safe to run twice."""
    services.close_petitions()


@job("votes.open_referendums")
def open_referendums(payload):
    """Scheduled votes open at midnight. Safe to run twice."""
    services.open_due_referendums()


@job("votes.close_referendums")
def close_referendums(payload):
    """Count the votes whose time is over. Safe to run twice."""
    services.close_referendums()


@job("votes.close_elections")
def close_elections(payload):
    """Count the elections whose time is over. Safe to run twice."""
    elections.close_elections()


@job("votes.yearly_elections")
def yearly_elections(payload):
    """Open a new election a month before the terms end. Safe to run twice."""
    elections.yearly_elections()
