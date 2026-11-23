from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.members.models import Member
from apps.votes import services
from apps.votes.models import Ballot, VoterRecord

from .conftest import open_vote, pool, rejected_ticket

pytestmark = pytest.mark.django_db


def setup(n=10, prefix="p", **kw):
    members = pool(n, prefix=prefix)
    r = open_vote(rejected_ticket(members[0]), **kw)
    return members, r


def test_a_scheduled_vote_opens_the_next_day_with_the_eligible_count_fixed():
    members = pool(10)
    r = services.schedule_referendum(rejected_ticket(members[0]), "Should we?")
    assert (
        r.status == "scheduled" and r.opens_at > timezone.now() and timezone.localtime(r.opens_at).hour == 0
    )  # 00:00 Berlin
    assert r.closes_at - r.opens_at == timedelta(days=14) and r.quorum_share == Decimal("0.2")
    assert services.open_due_referendums() == 0
    assert services.open_due_referendums(now=timezone.now() + timedelta(days=2)) == 1
    r.refresh_from_db()
    assert r.status == "open" and r.eligible_count == 10


def test_a_member_cannot_vote_twice():
    members, r = setup()
    services.cast(r, members[1], "yes")
    with pytest.raises(services.VoteError, match="already voted"):
        services.cast(r, members[1], "no")
    assert VoterRecord.objects.count() == 1 and Ballot.objects.count() == 1


def test_hf13_unverified_cannot_vote():
    members, r = setup()
    Member.objects.filter(pk=members[1].pk).update(status=Member.APPLICANT)
    members[1].refresh_from_db()
    with pytest.raises(services.VoteError):
        services.cast(r, members[1], "yes")
    assert not Ballot.objects.exists()


def test_a_ballot_row_has_no_member_and_no_time():
    names = {f.name for f in Ballot._meta.get_fields()}
    assert names == {"referendum", "election", "receipt", "choice"}
    kinds = {type(f).__name__ for f in Ballot._meta.get_fields()}
    assert not kinds & {"DateTimeField", "DateField"}
    assert "member" not in names and {f.name for f in VoterRecord._meta.get_fields()} >= {"member", "voted_on"}


def test_the_receipt_shows_the_stored_choice():
    members, r = setup()
    receipt = services.cast(r, members[1], "no")
    assert len(receipt) == 12 and services.check_receipt(receipt.lower()).choice == "no"
    assert services.check_receipt("NOSUCHCODE00") is None


def test_ballots_cannot_be_changed_or_deleted():
    members, r = setup()
    services.cast(r, members[1], "yes")
    with pytest.raises(ValueError):
        Ballot.objects.update(choice="no")
    with pytest.raises(ValueError):
        Ballot.objects.get().delete()


def test_a_vote_that_is_not_open_refuses():
    members = pool(5)
    r = services.schedule_referendum(rejected_ticket(members[0]), "Q?")
    with pytest.raises(services.VoteError, match="not open"):
        services.cast(r, members[1], "yes")


def test_the_quorum_fails_with_low_turnout():
    members, r = setup(10)
    services.cast(r, members[1], "yes")  # 1 of 10 is 10%, below 20%
    services.close_referendums(now=timezone.now() + timedelta(days=30))
    r.refresh_from_db()
    assert r.status == "closed" and r.result["quorum_met"] is False and r.result["approved"] is False


def test_abstentions_count_for_the_quorum_but_not_for_the_majority():
    members, r = setup(10)
    services.cast(r, members[1], "abstain")
    services.cast(r, members[2], "yes")
    services.close_referendums(now=timezone.now() + timedelta(days=30))
    r.refresh_from_db()
    assert r.result["quorum_met"] and r.result["yes"] == 1 and r.result["abstain"] == 1 and r.result["approved"]


def test_a_tie_is_not_a_simple_majority():
    members, r = setup(10)
    services.cast(r, members[1], "yes")
    services.cast(r, members[2], "no")
    services.close_referendums(now=timezone.now() + timedelta(days=30))
    r.refresh_from_db()
    assert r.result["quorum_met"] and r.result["approved"] is False


def test_a_two_thirds_majority_is_computed_correctly():
    members, r = setup(10, majority="two_thirds")
    for m, v in zip(members[1:4], ["yes", "yes", "no"], strict=True):
        services.cast(r, m, v)
    services.close_referendums(now=timezone.now() + timedelta(days=30))
    r.refresh_from_db()
    assert r.result["approved"] is True  # 2 of 3 is exactly two thirds
    members, r2 = setup(10, prefix="q", majority="two_thirds")
    for m, v in zip(members[1:6], ["yes", "yes", "yes", "no", "no"], strict=True):
        services.cast(r2, m, v)
    services.close_referendums(now=timezone.now() + timedelta(days=60))
    r2.refresh_from_db()
    assert r2.result["approved"] is False  # 3 of 5 is 60%


def test_a_ranked_vote_is_counted_with_instant_runoff():
    members, r = setup(10, method="ranked_irv", options=["A", "B", "C"])
    ballots = [["A", "B"], ["A"], ["B", "A"], ["B", "C"], ["C", "B"]]
    for m, b in zip(members[1:6], ballots, strict=True):
        services.cast(r, m, b)
    with pytest.raises(services.VoteError):
        services.cast(r, members[6], ["A", "A"])
    services.close_referendums(now=timezone.now() + timedelta(days=30))
    r.refresh_from_db()
    assert r.result["winner"] == "B" and r.result["approved"] and r.result["rounds"][0]["eliminated"] == "C"


def test_the_against_brief_lists_the_panels_no_reasons():
    from apps.tickets import services as ts
    from apps.tickets.tests.conftest import answer, open_seats, ticket_with_brief

    members = pool(40)
    ticket = ticket_with_brief(members[0])
    answer(open_seats(ticket)[0], "no", reason="This is far too expensive for us.")
    r = services.schedule_referendum(ticket, "Should we?")
    assert "far too expensive" in r.brief_against_md and r.brief_for_md == "The brief."
    assert ts and r


def test_the_pages(client):
    members, r = setup()
    client.force_login(members[1].user)
    assert client.get(reverse("votes:list")).status_code == 200
    assert "Yes" in client.get(reverse("votes:referendum", args=[r.pk])).content.decode()
    # voting is a sensitive action: without a recent login it is never served
    response = client.post(reverse("votes:cast", args=[r.pk]), {"choice": "yes"})
    assert response.status_code in (302, 403) and not Ballot.objects.exists()
    receipt = services.cast(r, members[2], "yes")
    html = client.get(reverse("votes:check"), {"code": receipt}).content.decode()
    assert "yes" in html and "Counted in" in html


def test_ballots_are_protected_by_the_database_too():
    from django.db import connection

    from apps.core.sql import triggers_present

    members, r = setup()
    services.cast(r, members[1], "yes")
    if not all(triggers_present(["votes_ballot", "votes_voterrecord"]).values()):
        pytest.skip("this database has no trigger privilege; the model guards still apply")
    with connection.cursor() as cursor, pytest.raises(Exception, match="append-only"):  # noqa: B017,PT011
        cursor.execute("UPDATE votes_ballot SET receipt = receipt")
    with connection.cursor() as cursor, pytest.raises(Exception, match="append-only"):  # noqa: B017,PT011
        cursor.execute("DELETE FROM votes_voterrecord")
