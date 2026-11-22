from datetime import timedelta

import pytest
from django.utils import timezone

from apps.members.models import Member
from apps.tickets import mediation
from apps.units.models import HoursEntry

from .conftest import CHECK, make_member, open_seats, pool

pytestmark = pytest.mark.django_db


def setup(mediators=5, others=20):
    people = pool(mediators + others)
    Member.objects.filter(pk__in=[m.pk for m in people[:mediators]]).update(is_mediator=True)
    a, b = make_member("a@x.org", "Ada"), make_member("b@x.org", "Bo")
    ticket = mediation.open_mediation(
        a, "A dispute", "We disagree", parties_members=[b], brief="The dispute.", check=CHECK
    )
    ticket.refresh_from_db()
    return people, a, b, ticket


def mediator_members(ticket):
    return list(mediation.mediators(ticket))


def test_three_mediators_are_drawn_from_the_volunteers_and_never_the_parties():
    people, a, b, ticket = setup()
    Member.objects.filter(pk__in=[a.pk, b.pk]).update(is_mediator=True, joined_at=timezone.now() - timedelta(days=300))
    ticket2 = mediation.open_mediation(a, "Again", "x", parties_members=[b], brief="b", check=CHECK)
    for t in (ticket, ticket2):
        ms = mediator_members(t)
        assert len(ms) == 3 and a not in ms and b not in ms
    assert all(m.is_mediator for m in mediator_members(ticket))
    assert ticket.status == "confirming" and "until" in ticket.status_note


def test_a_small_pool_draws_from_everyone_eligible():
    people, a, b, ticket = setup(mediators=1)
    ms = mediator_members(ticket)
    assert len(ms) == 3 and sum(m.is_mediator for m in ms) <= 1 and a not in ms


def test_an_agreement_closes_the_ticket_when_both_sides_confirm():
    people, a, b, ticket = setup()
    m = mediator_members(ticket)[0]
    mediation.post(ticket, m, "Let us talk")
    assert len(mediation.messages_for(ticket, a)) == 1 and mediation.messages_for(ticket, people[10]) == []
    mediation.propose_agreement(ticket, m, "Ada pays Bo a coffee.")
    mediation.confirm_agreement(ticket, a)
    ticket.refresh_from_db()
    assert ticket.status == "confirming"
    mediation.confirm_agreement(ticket, b)
    ticket.refresh_from_db()
    assert ticket.status == "done" and ticket.action_result["outcome"] == "agreement"


def test_only_the_parties_confirm():
    people, a, b, ticket = setup()
    m = mediator_members(ticket)[0]
    mediation.propose_agreement(ticket, m, "x")
    with pytest.raises(mediation.MediationError):
        mediation.confirm_agreement(ticket, people[15])


def test_no_agreement_starts_a_panel_that_reads_both_positions():
    people, a, b, ticket = setup()
    mediation.write_position(ticket, a, "I am right.")
    mediation.write_position(ticket, b, "No, I am.")
    mediation.no_agreement(ticket, mediator_members(ticket)[0])
    ticket.refresh_from_db()
    assert ticket.status == "panel" and len(open_seats(ticket, "panel")) == 12
    assert "I am right." in ticket.brief_md and "No, I am." in ticket.brief_md
    earlier = {m.pk for m in mediator_members(ticket)}
    assert not earlier & {s.member_id for s in open_seats(ticket, "panel")}


def test_a_position_has_at_most_300_words():
    people, a, b, ticket = setup()
    with pytest.raises(mediation.MediationError):
        mediation.write_position(ticket, a, "word " * 301)


def test_the_deadline_sends_the_matter_to_a_panel():
    people, a, b, ticket = setup()
    assert mediation.process_deadlines() == 0
    assert mediation.process_deadlines(now=timezone.now() + timedelta(days=15)) == 1  # one ticket, three seats
    ticket.refresh_from_db()
    assert ticket.status == "panel"
    assert mediation.process_deadlines(now=timezone.now() + timedelta(days=15)) == 0


def test_the_panel_decides_between_the_sides():
    from .conftest import answer

    people, a, b, ticket = setup()
    mediation.no_agreement(ticket, a)
    for s in open_seats(ticket, "panel")[:7]:
        answer(s, "yes")
    ticket.refresh_from_db()
    assert ticket.status == "done" and "the asking side" in ticket.action_result["text"]


def test_mediator_time_is_paid_up_to_six_hours():
    people, a, b, ticket = setup()
    m = mediator_members(ticket)[0]
    entry = mediation.record_time(ticket, m, 240)
    assert entry.status == "paid" and HoursEntry.objects.filter(ref_type="mediation").count() == 1
    with pytest.raises(mediation.MediationError):
        mediation.record_time(ticket, m, 150)
    mediation.record_time(ticket, m, 120)
    with pytest.raises(mediation.MediationError):
        mediation.record_time(ticket, a, 10)


def test_mediators_are_not_replaced_by_the_seat_deadline_job():
    from apps.tickets import confirm

    people, a, b, ticket = setup()
    confirm.process_deadlines(now=timezone.now() + timedelta(days=30))
    assert len(mediator_members(ticket)) == 3


def test_a_member_can_volunteer_as_a_mediator_on_my_account(client):
    from django.urls import reverse

    m = make_member("m@x.org", "Mo")
    client.force_login(m.user)
    assert "Join the pool of mediators" in client.get(reverse("members:my_account")).content.decode()
    client.post(reverse("members:mediator_toggle"))
    m.refresh_from_db()
    assert m.is_mediator
    client.post(reverse("members:mediator_toggle"))
    m.refresh_from_db()
    assert not m.is_mediator


def test_the_mediation_pages_are_only_for_the_parties_and_mediators(client):
    from django.urls import reverse

    people, a, b, ticket = setup()
    outsider = people[15]
    client.force_login(outsider.user)
    assert client.get(reverse("tickets:mediation", args=[ticket.number])).status_code == 403
    client.force_login(a.user)
    assert client.get(reverse("tickets:mediation", args=[ticket.number])).status_code == 200
    client.post(reverse("tickets:mediation_action", args=[ticket.number, "post"]), {"body": "Hello"})
    assert ticket.mediation_messages.count() == 1
