"""The acceptance check of phase 06 (plan/phase_06_tickets_confirmers.md)."""

import pytest

from apps.plan import check as plan_check
from apps.tickets import draw
from apps.tickets.models import Ticket
from apps.units import services as us
from apps.units.models import HoursEntry

from .conftest import answer, make_member, open_seats, pool

pytestmark = pytest.mark.django_db


def red(monkeypatch):
    result = plan_check.CheckResult([plan_check.CheckPoint("red", "This trade is on the test red list")])
    monkeypatch.setattr(plan_check, "check", lambda request: result)


def test_phase_06_acceptance(monkeypatch):
    pool(40)
    red(monkeypatch)
    real_eligible, seen = draw.eligible, []

    def recording_eligible(ticket, round="confirmers"):
        found = real_eligible(ticket, round)
        seen.append((ticket.number, round, [m.number for m in found]))
        return found

    monkeypatch.setattr(draw, "eligible", recording_eligible)
    data = {"name": "Bakery", "kind": "production", "description": "Bread"}

    # 1. A unit whose trade is on a red list is paused, and a ticket is created.
    unit = us.open_unit(make_member("founder@x.org", "Founder"), data)
    ticket = Ticket.objects.get(type="open_unit")
    assert unit.status == "paused" and ticket.status == "confirming"

    # 2. Four seats answer the check question and vote yes: the unit opens, each seat got 30 paid minutes.
    seats = open_seats(ticket)
    assert len(seats) == 4
    for s in seats:
        answer(s, "yes")
    unit.refresh_from_db()
    ticket.refresh_from_db()
    assert unit.status == "trial" and ticket.status == "done"
    assert all(HoursEntry.objects.get(pk=s.paid_entry_id).minutes == 30 for s in open_seats(ticket))

    # 3. With one "no": a panel of 12 is drawn, and 7 yes votes open the unit.
    unit2 = us.open_unit(make_member("second@x.org", "Second"), {**data, "name": "Mill"})
    ticket2 = Ticket.objects.filter(type="open_unit").exclude(pk=ticket.pk).get()
    answer(open_seats(ticket2)[0], "no")
    ticket2.refresh_from_db()
    assert ticket2.status == "panel" and len(open_seats(ticket2, "panel")) == 12
    for s in open_seats(ticket2, "panel")[:7]:
        answer(s, "yes")
    unit2.refresh_from_db()
    assert unit2.status == "trial"

    # 4. `reproduce` gives the same seats, from the list of eligible numbers an auditor was given.
    for t in (ticket, ticket2):
        for confirmation in t.confirmations.filter(parent__isnull=True):
            numbers = [n for (number, r, n) in seen if number == t.number and r == confirmation.round][0]
            drawn = [s.member.number for s in confirmation.seats.order_by("drawn_order")]
            assert draw.reproduce(confirmation, numbers) == drawn
            with pytest.raises(ValueError):
                draw.reproduce(confirmation, numbers[:-1])  # a different list is refused
