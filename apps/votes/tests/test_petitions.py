from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.members.models import Member
from apps.votes import services
from apps.votes.models import Petition, Referendum

from .conftest import pool, rejected_ticket

pytestmark = pytest.mark.django_db


def test_the_threshold_is_reached_and_the_referendum_is_scheduled():
    members = pool(12)
    ticket = rejected_ticket(members[0])
    petition = services.open_petition(ticket, members[1], "Should we do this?")
    assert petition.threshold == 5 and petition.signatures.count() == 1  # the opener signs
    ticket.refresh_from_db()
    assert ticket.status == "petition"
    for m in members[2:5]:
        services.sign(petition, m)
    assert not Referendum.objects.exists()
    services.sign(petition, members[5])
    petition.refresh_from_db()
    assert petition.status == "succeeded"
    r = Referendum.objects.get()
    assert r.status == "scheduled" and r.question == "Should we do this?" and r.ticket == ticket
    ticket.refresh_from_db()
    assert ticket.status == "referendum" and ticket.decision_method == "referendum"


def test_the_threshold_grows_with_the_number_of_members():
    pool(300)
    assert services.petition_threshold() == 6  # 2% of 300


def test_hf13_an_unverified_member_cannot_sign_or_open():
    members = pool(8)
    applicant = pool(1, prefix="app")[0]
    Member.objects.filter(pk=applicant.pk).update(status=Member.APPLICANT)
    applicant.refresh_from_db()
    ticket = rejected_ticket(members[0])
    with pytest.raises(services.VoteError):
        services.open_petition(ticket, applicant)
    petition = services.open_petition(ticket, members[1])
    with pytest.raises(services.VoteError):
        services.sign(petition, applicant)


def test_one_signature_each_and_one_open_petition_per_ticket():
    members = pool(8)
    ticket = rejected_ticket(members[0])
    petition = services.open_petition(ticket, members[1])
    with pytest.raises(services.VoteError):
        services.sign(petition, members[1])
    ticket.refresh_from_db()
    with pytest.raises(services.VoteError):
        services.open_petition(ticket, members[2])


def test_a_petition_needs_the_petition_time_of_a_rejected_ticket():
    from apps.tickets import services as ticket_services

    members = pool(8)
    open_ticket = ticket_services.create_ticket("idea", members[0], "Idea")
    with pytest.raises(services.VoteError):
        services.open_petition(open_ticket, members[1])
    late = rejected_ticket(members[0], days=-1)
    with pytest.raises(services.VoteError):
        services.open_petition(late, members[1])


def test_a_request_for_a_vote_can_be_petitioned_at_any_time():
    from apps.tickets import services as ticket_services

    members = pool(8)
    ticket = ticket_services.create_ticket("referendum_request", members[0], "Let us vote on this")
    assert services.open_petition(ticket, members[1])


def test_a_petition_past_its_time_fails_and_the_ticket_is_rejected_again():
    members = pool(8)
    ticket = rejected_ticket(members[0])
    petition = services.open_petition(ticket, members[1])
    assert services.close_petitions() == 0
    assert services.close_petitions(now=timezone.now() + timedelta(days=15)) == 1
    petition.refresh_from_db()
    ticket.refresh_from_db()
    assert petition.status == "failed" and ticket.status == "rejected"
    with pytest.raises(services.VoteError):
        services.sign(petition, members[2])


def test_the_page_shows_the_count_and_never_the_names(client):
    members = pool(8)
    ticket = rejected_ticket(members[0])
    petition = services.open_petition(ticket, members[1])
    services.sign(petition, members[2])
    client.force_login(members[3].user)
    html = client.get(reverse("votes:petition", args=[petition.pk])).content.decode()
    assert "2 of 5 signatures" in html and members[1].display_name not in html and members[2].display_name not in html
    client.post(reverse("votes:sign", args=[petition.pk]))
    assert Petition.objects.get().signatures.count() == 3


def test_the_ticket_can_open_a_petition_through_the_page(client):
    members = pool(8)
    ticket = rejected_ticket(members[0])
    client.force_login(members[1].user)
    response = client.post(reverse("votes:open_petition", args=[ticket.number]), {"question": "Vote on this?"})
    assert response.status_code == 302 and Petition.objects.get().question == "Vote on this?"
