from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.plan import apply, services, variants, vote
from apps.plan.models import PlanComment
from apps.votes import services as votes
from apps.votes.models import Referendum

from .conftest import drafting_group

pytestmark = pytest.mark.django_db


def _three_plans(period, member):
    names = ["Plan A", "Plan B", "Plan C"]
    made = []
    for name in names:
        v = variants.create_variant(member, period, name)
        variants.set_months(member, v, [100] * 12, [2000] * 12)
        variants.submit_variant(member, v)
        made.append(v)
    return made


def _setup(year=2030):
    period, g, members = drafting_group(25, year=year)
    member = g.seats.first().member
    _three_plans(period, member)
    variants.finish_drafting(period)
    period.refresh_from_db()
    return period, members


def _open(period):
    ref = vote.start_vote(period, on=date(period.starts_on.year - 1, 11, 1))
    votes.open_due_referendums(now=timezone.now() + timedelta(days=2))
    ref.refresh_from_db()
    return ref


def test_comments_are_open_to_members_after_drafting_and_the_brief_shows_the_tax():
    period, members = _setup()
    v = period.variants.get(name="Plan A")
    c = vote.comment(v, members[0], "I like it")
    assert PlanComment.objects.get() == c
    brief = vote.brief_for(v)
    assert "Implied flat tax" in brief and "no forecast" in brief
    with pytest.raises(services.PlanError, match="write"):
        vote.comment(v, members[0], " ")


def test_three_variants_and_the_irv_winner():
    period, members = _setup()
    ref = _open(period)
    assert ref.method == "ranked_irv" and ref.options == ["Plan A", "Plan B", "Plan C"]
    ballots = (
        [["Plan A", "Plan B", "Plan C"]] * 10
        + [["Plan B", "Plan C", "Plan A"]] * 8
        + [["Plan C", "Plan B", "Plan A"]] * 7
    )
    for member, ballot in zip(members, ballots, strict=True):
        votes.cast(ref, member, ballot)
    votes.close_referendums(now=timezone.now() + timedelta(days=40))
    period.refresh_from_db()
    assert period.status == "adopted" and period.adopted_variant.name == "Plan B"  # C drops out, its votes go to B


def test_a_failed_quorum_extends_the_current_plan_and_repeats_the_vote():
    period, members = _setup()
    ref = _open(period)
    votes.cast(ref, members[0], ["Plan A"])
    votes.cast(ref, members[1], ["Plan B"])
    votes.close_referendums(now=timezone.now() + timedelta(days=40))
    period.refresh_from_db()
    assert period.status == "voting" and period.adopted_variant is None
    assert period.revote_on and period.extended_until == period.revote_on
    assert apply.repeat_vote(on=period.revote_on - timedelta(days=1)) == 0
    assert apply.repeat_vote(on=period.revote_on) == 1
    assert Referendum.objects.filter(ticket__action_payload__period=period.pk).count() == 2
