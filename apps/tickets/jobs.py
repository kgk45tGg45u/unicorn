from apps.core.jobs import job

from . import confirm, sampling


@job("tickets.seat_deadlines")
def seat_deadlines(payload):
    """Replace silent seats, send reminders, and queue the next run. Safe to run twice."""
    confirm.process_deadlines()
    confirm.schedule_deadline_job()


@job("tickets.one_person_checks")
def one_person_checks(payload):
    """Once a month: a random sample of the one-person units gets a check ticket. Safe to run twice."""
    sampling.one_person_checks()
