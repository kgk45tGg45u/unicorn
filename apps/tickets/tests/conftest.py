from io import StringIO

import pytest
from django.core.management import call_command

from apps.units.tests.conftest import make_member, make_unit  # noqa: F401


@pytest.fixture(autouse=True)
def defaults_loaded(db):
    call_command("load_defaults", stdout=StringIO())


CHECK = {"question": "What is asked?", "choices": ["A", "B", "C"], "correct": 1, "hint": "the first paragraph"}


def pool(n, prefix="p", months=6):
    """n verified members who have been members long enough to be drawn."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.members.models import Member

    members = [make_member(f"{prefix}{i}@x.org", f"{prefix.upper()}{i}") for i in range(n)]
    Member.objects.filter(pk__in=[m.pk for m in members]).update(joined_at=timezone.now() - timedelta(days=30 * months))
    return members


def ticket_with_brief(author, type="delegate", **kw):
    from apps.tickets import services

    return services.create_ticket(type, author, "A ticket", brief="The brief.", check=CHECK, **kw)


def answer(seat, vote="yes", reason="This is a reason that is long enough."):
    from apps.tickets import confirm

    seat.refresh_from_db()
    if not seat.check_passed:
        assert confirm.answer_check(seat, seat.confirmation.ticket.check_correct)
    return confirm.cast(seat, vote, reason if vote == "no" else "")


def open_seats(ticket, round_="confirmers"):
    from django.db.models import Q

    from apps.tickets.models import Seat

    return list(
        Seat.objects.filter(confirmation__ticket=ticket, replaced=False)
        .filter(Q(confirmation__round=round_) | Q(confirmation__parent__round=round_))
        .order_by("id")
    )
