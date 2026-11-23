from io import StringIO

import pytest
from django.core.management import call_command

from apps.tickets.tests.conftest import CHECK, answer, make_member, make_unit, open_seats, pool  # noqa: F401


@pytest.fixture(autouse=True)
def defaults_loaded(db):
    call_command("load_defaults", stdout=StringIO())


def rejected_ticket(author, days=14, type="idea"):
    """A ticket the panel rejected, with its petition time still running."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.tickets import services
    from apps.tickets.models import Ticket

    ticket = services.create_ticket(type, author, "A bold idea", brief="The brief.")
    Ticket.objects.filter(pk=ticket.pk).update(status="rejected", petition_until=timezone.now() + timedelta(days=days))
    ticket.refresh_from_db()
    return ticket


def open_vote(ticket, question="Should we?", **kw):
    """Schedule a referendum and open it at once."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.votes import services

    r = services.schedule_referendum(ticket, question, **kw)
    services.open_due_referendums(now=timezone.now() + timedelta(days=2))
    r.refresh_from_db()
    return r
