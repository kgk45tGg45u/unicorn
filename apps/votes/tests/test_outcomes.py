from datetime import timedelta

import pytest
from django.utils import timezone

from apps.plan import check as plan_check  # noqa: F401
from apps.tickets import services as ticket_services
from apps.tickets.models import Ticket
from apps.votes import services
from apps.votes.models import Referendum

from .conftest import CHECK, make_unit, pool

pytestmark = pytest.mark.django_db


def forced_vote(ticket, members, voters, choices):
    """A petition reaches its threshold, the vote opens, the given members vote, and the vote closes."""
    p = services.open_petition(ticket, members[1])
    for m in members[2 : 2 + p.threshold]:
        p.refresh_from_db()
        if p.status == "open":
            services.sign(p, m)
    r = Referendum.objects.get(ticket=ticket)
    services.open_due_referendums(now=timezone.now() + timedelta(days=2))
    for m, c in zip(voters, choices, strict=False):
        services.cast(r, m, c)
    services.close_referendums(now=timezone.now() + timedelta(days=30))
    r.refresh_from_db()
    ticket.refresh_from_db()
    return r


def rejected_open_unit(members):
    unit = make_unit("bakery", status="paused")
    ticket = ticket_services.create_ticket(
        "open_unit",
        members[0],
        "Open the bakery",
        brief="The brief.",
        check=CHECK,
        plan_check={"color": "red", "points": []},
        action_payload={"unit_id": unit.pk},
        open_now=False,
    )
    Ticket.objects.filter(pk=ticket.pk).update(status="rejected", petition_until=timezone.now() + timedelta(days=10))
    ticket.refresh_from_db()
    return unit, ticket


def test_an_approved_referendum_runs_the_tickets_action():
    members = pool(14)
    unit, ticket = rejected_open_unit(members)
    r = forced_vote(ticket, members, members[:8], ["yes"] * 6 + ["no"] * 2)
    unit.refresh_from_db()
    assert r.result["approved"] and ticket.status == "done" and unit.status == "trial"


def test_a_failed_quorum_rejects_the_ticket_with_the_counts():
    members = pool(14)
    unit, ticket = rejected_open_unit(members)
    r = forced_vote(ticket, members, members[:2], ["yes", "yes"])  # 2 of 14 is below 20%
    unit.refresh_from_db()
    assert (
        not r.result["quorum_met"]
        and ticket.status == "rejected"
        and "Too few members voted (2 of 14)" in ticket.status_note
    )
    assert unit.status == "paused"


def test_a_no_majority_rejects_it():
    members = pool(14)
    unit, ticket = rejected_open_unit(members)
    r = forced_vote(ticket, members, members[:6], ["yes"] * 2 + ["no"] * 4)
    ticket.refresh_from_db()
    assert (
        not r.result["approved"] and ticket.status == "rejected" and "2 voted yes and 4 voted no" in ticket.status_note
    )


def test_a_petition_forced_referendum_decides_finally():
    members = pool(14)
    unit, ticket = rejected_open_unit(members)
    forced_vote(ticket, members, members[:6], ["no"] * 6)
    ticket.refresh_from_db()
    assert ticket.petition_until is None
    with pytest.raises(services.VoteError):
        services.open_petition(ticket, members[2])


def test_a_request_for_a_vote_has_no_action_unless_it_names_a_change():
    members = pool(14)
    ticket = ticket_services.create_ticket("referendum_request", members[0], "Shall we have a garden?")
    r = forced_vote(ticket, members, members[:6], ["yes"] * 6)
    assert ticket.status == "approved" and ticket.action == "" and r.result["approved"]
