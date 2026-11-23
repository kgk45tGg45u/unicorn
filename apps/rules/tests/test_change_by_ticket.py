from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.rules.models import Parameter, ParameterChange
from apps.rules.services import get_param, set_param
from apps.tickets import services as ts
from apps.tickets.models import Ticket
from apps.tickets.tests.conftest import CHECK, answer, make_member, open_seats, pool
from apps.votes import services as votes
from apps.votes.models import Referendum

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def defaults_loaded(db):
    from io import StringIO

    from django.core.management import call_command

    call_command("load_defaults", stdout=StringIO())


CONFIRM_KEY = "logistics.default_cover_radius_km"
REFERENDUM_KEY = "governance.confirmers.size"


def propose(author, key, value, reason="Because it helps"):
    return ts.create_parameter_change(author, key, value, reason, brief="Why we should do this.", check=CHECK)


def test_hf16_confirm_tier_needs_confirmers():
    members = pool(10)
    ticket = propose(members[0], CONFIRM_KEY, 15)
    assert get_param(CONFIRM_KEY) == Decimal("10")  # nothing changes before the decision
    seats = open_seats(ticket)
    for s in seats[:3]:
        answer(s, "yes")
    assert get_param(CONFIRM_KEY) == Decimal("10")
    answer(seats[3], "yes")
    ticket.refresh_from_db()
    assert get_param(CONFIRM_KEY) == Decimal("15") and ticket.status == "done"
    change = ParameterChange.objects.filter(parameter__key=CONFIRM_KEY).first()
    assert (
        change.decided_by == ticket.number and change.decided_tier == "confirm" and change.reason == "Because it helps"
    )


def test_the_value_is_checked_against_the_bounds_before_the_ticket_opens():
    members = pool(6)
    with pytest.raises(ts.TicketError, match="may not be higher"):
        propose(members[0], CONFIRM_KEY, 5000)
    with pytest.raises(ts.TicketError):
        propose(members[0], "no.such.key", 1)
    assert not Ticket.objects.exists()


def test_hf16_referendum_tier_needs_referendum():
    members = pool(14)
    ticket = propose(members[0], REFERENDUM_KEY, 5)
    for s in open_seats(ticket):
        answer(s, "yes")  # the completeness check
    ticket.refresh_from_db()
    assert get_param(REFERENDUM_KEY) == 4 and ticket.status == "referendum"
    r = Referendum.objects.get(ticket=ticket)
    votes.open_due_referendums(now=timezone.now() + timedelta(days=2))
    for m in members[:6]:
        votes.cast(r, m, "yes")
    assert get_param(REFERENDUM_KEY) == 4
    votes.close_referendums(now=timezone.now() + timedelta(days=30))
    assert get_param(REFERENDUM_KEY) == 5
    change = ParameterChange.objects.filter(parameter__key=REFERENDUM_KEY).first()
    assert change.decided_tier == "referendum" and change.decided_by == ticket.number


def test_hf16_hard_tier_refused():
    members = pool(6)
    ticket = propose(members[0], "economy.uniq_per_hour", 1)
    ticket.refresh_from_db()
    assert (
        ticket.status == "rejected" and "hard-frame change" in ticket.status_note and not ticket.confirmations.exists()
    )
    with pytest.raises(Exception):  # noqa: B017,PT011
        set_param("economy.uniq_per_hour", 1, decided_by=ticket.number, decided_tier="referendum", reason="x")


def test_a_plan_tier_default_is_sent_to_the_plan_with_two_offers():
    members = pool(6)
    ticket = propose(members[0], "economy.social_share_start", 0.05)
    ticket.refresh_from_db()
    assert ticket.status == "rejected" and "yearly plan" in ticket.status_note and not ticket.confirmations.exists()
    request = ts.turn_parameter_ticket(ticket, members[0], "referendum_request")
    assert request.type == "referendum_request" and request.action == "change_parameter"
    assert request.action_payload["key"] == "economy.social_share_start"
    proposal = ts.turn_parameter_ticket(ticket, members[0], "plan_proposal")
    assert proposal.type == "plan_proposal"


def test_a_vote_on_a_plan_tier_default_changes_it_at_the_referendum_tier():
    members = pool(14)
    ticket = propose(members[0], "economy.social_share_start", 0.05)
    request = ts.turn_parameter_ticket(ticket, members[0], "referendum_request")
    p = votes.open_petition(request, members[1])
    for m in members[2:7]:
        p.refresh_from_db()
        if p.status == "open":
            votes.sign(p, m)
    r = Referendum.objects.get(ticket=request)
    votes.open_due_referendums(now=timezone.now() + timedelta(days=2))
    for m in members[:6]:
        votes.cast(r, m, "yes")
    votes.close_referendums(now=timezone.now() + timedelta(days=30))
    assert get_param("economy.social_share_start") == Decimal("0.05")


def test_the_rules_page_links_to_the_ticket_in_its_history(client):
    members = pool(10)
    ticket = propose(members[0], CONFIRM_KEY, 15)
    for s in open_seats(ticket):
        answer(s, "yes")
    client.force_login(members[1].user)
    html = client.get(reverse("rules:history", args=[CONFIRM_KEY])).content.decode()
    assert f"/tickets/{ticket.number}/" in html
    assert "Propose a change" in client.get(reverse("rules:index")).content.decode()
    form = client.get(reverse("rules:propose", args=[CONFIRM_KEY])).content.decode()
    assert "4 random members" in form and "0.5" in form  # the tier in words and the lowest allowed value


def test_the_propose_form_creates_the_ticket(client):
    members = pool(10)
    client.force_login(members[0].user)
    response = client.post(
        reverse("rules:propose", args=[CONFIRM_KEY]),
        {"new_value": "12", "reason": "Larger area", "brief": "Why.", "check_question": "q?", "answer_0": "a",
         "answer_1": "b", "answer_2": "c", "correct": "1"},
    )  # fmt: skip
    assert response.status_code == 302
    assert (
        Ticket.objects.get().action_payload["new_value"] == 12
        or Ticket.objects.get().action_payload["new_value"] == "12"
    )
    assert make_member and Parameter
