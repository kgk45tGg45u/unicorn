from datetime import timedelta

import pytest
from django.utils import timezone

from apps.votes import elections, services
from apps.votes.models import Ballot, Election, Term

from .conftest import pool

pytestmark = pytest.mark.django_db


def run(role="auditor", n=12, approvals=None):
    """An election with the first 6 members standing; voters approve the given candidate indexes."""
    members = pool(n)
    e = elections.open_election(role)
    for m in members[:6]:
        elections.stand(e, m, "Pick me")
    for voter, picks in zip(members[6:], approvals or [], strict=False):
        elections.cast(e, voter, [members[i].pk for i in picks])
    return members, e


def close(e):
    """The voting time is over: close the election now, so the terms start now."""
    Election.objects.filter(pk=e.pk).update(closes_at=timezone.now() - timedelta(seconds=1))
    return elections.close_elections()


def test_the_top_n_approvals_win():
    approvals = [[0, 1, 2], [0, 1, 3], [0, 2, 3], [0, 4], [1, 2]]
    members, e = run(approvals=approvals)
    assert close(e) == 1
    e.refresh_from_db()
    # approvals: 0:4, 1:3, 2:3, 3:2, 4:1, 5:0
    assert sorted(e.result["winners"]) == sorted(m.number for m in members[:3])
    assert e.status == "closed" and e.result["voters"] == 5 and not e.result["tie_broken_by_seed"]
    assert {t.member_id for t in Term.objects.all()} == {m.pk for m in members[:3]}


def test_a_term_lasts_one_year():
    members, e = run(approvals=[[0, 1, 2]])
    close(e)
    term = Term.objects.first()
    assert term.ends_at - term.starts_at == timedelta(days=365)
    assert elections.current_members("auditor").count() == 3
    assert elections.current_members("auditor", now=timezone.now() + timedelta(days=400)).count() == 0


def test_a_tie_at_the_edge_is_broken_by_a_seed_anyone_can_repeat():
    members, e = run(approvals=[[0, 1, 2, 3], [0, 1, 2, 3]])  # four candidates tie for the last... 3 seats
    close(e)
    e.refresh_from_db()
    assert e.result["tie_broken_by_seed"] is True and len(e.result["winners"]) == 3
    again = elections._winners({m.pk: 2 for m in members[:4]}, 3, "x")
    assert again == elections._winners({m.pk: 2 for m in members[:4]}, 3, "x")


def test_ballots_are_secret_and_one_vote_each():
    members, e = run(approvals=[[0]])
    with pytest.raises(services.VoteError, match="already voted"):
        elections.cast(e, members[6], [members[1].pk])
    with pytest.raises(services.VoteError, match="only people who stand"):
        elections.cast(e, members[7], [members[11].pk])
    assert Ballot.objects.get().election == e and not hasattr(Ballot.objects.get(), "member")


def test_hf13_an_unverified_member_cannot_stand_or_vote():
    from apps.members.models import Member

    members, e = run()
    Member.objects.filter(pk=members[9].pk).update(status=Member.APPLICANT)
    members[9].refresh_from_db()
    with pytest.raises(services.VoteError):
        elections.stand(e, members[9])
    with pytest.raises(services.VoteError):
        elections.cast(e, members[9], [])


def test_the_trust_review_group_has_the_size_from_the_defaults():
    members, e = run(role="trust_review", approvals=[[0, 1, 2, 3, 4]])
    assert e.seats == 3
    close(e)
    assert Term.objects.filter(role="trust_review").count() == 3


def test_one_election_per_role_and_a_yearly_one_a_month_before_the_terms_end():
    members, e = run(approvals=[[0, 1, 2]])
    with pytest.raises(services.VoteError):
        elections.open_election("auditor")
    close(e)
    assert elections.yearly_elections() == 0
    assert elections.yearly_elections(now=timezone.now() + timedelta(days=340)) == 1
    assert Election.objects.filter(role="auditor", status="open").count() == 1
    assert elections.yearly_elections(now=timezone.now() + timedelta(days=341)) == 0


def test_the_first_elections_are_started_by_a_vote_not_by_the_job():
    pool(5)
    assert elections.yearly_elections() == 0  # nobody has ever been elected: a vote must start it
    from apps.tickets import services as ts
    from apps.tickets.models import Ticket

    t = ts.create_ticket(
        "poll", None, "Start the elections", action="start_elections", action_payload={"roles": ["auditor"]}
    )
    assert elections.start_first_elections(t) == {"opened": ["auditor"]}
    assert Ticket.objects.count() == 1


def test_audit_failures_go_to_the_auditors():
    from apps.ledger.models import AuditRun
    from apps.tickets import briefs
    from apps.tickets.models import Seat

    members, e = run(n=40, approvals=[[0, 1, 2]] * 4)
    close(e)
    run_ = AuditRun.objects.create(
        started_at=timezone.now(), finished_at=timezone.now(), ok=False, last_seq=0, last_hash="0", findings=["Bad"]
    )
    ticket = briefs.audit_failure(run_)
    auditors = {m.pk for m in elections.current_members("auditor")}
    seated = set(Seat.objects.filter(confirmation__ticket=ticket).values_list("member_id", flat=True))
    assert seated and seated <= auditors


def test_the_start_elections_action_is_registered_and_runs_on_approval():
    from apps.tickets import actions
    from apps.tickets import services as ts
    from apps.tickets.tests.conftest import answer, open_seats

    assert "start_elections" in actions.ACTIONS
    pool(20)
    t = ts.create_ticket(
        "task_list", None, "x", brief="b", check={"question": "q", "choices": ["a", "b", "c"], "correct": 0},
        action="start_elections", action_payload={"roles": ["auditor"]},
    )  # fmt: skip
    for s in open_seats(t):
        answer(s, "yes")
    t.refresh_from_db()
    assert t.status == "done" and Election.objects.filter(role="auditor", status="open").exists()


def test_the_jobs_run():
    from apps.core.jobs import JOBS

    assert "votes.close_elections" in JOBS and "votes.yearly_elections" in JOBS
    JOBS["votes.close_elections"]({})
    JOBS["votes.yearly_elections"]({})
