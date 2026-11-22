from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.units import council_rules, services
from apps.units.models import CouncilRules

from .conftest import make_member, make_unit

pytestmark = pytest.mark.django_db


def council(n=3, rule="majority", quorum="0.5", tag="a"):
    unit = make_unit(f"bakery-{tag}")
    people = [make_member(f"m{i}{tag}@x.org", f"M{i}") for i in range(n)]
    services.add_first_worker(unit, people[0])
    for p in people[1:]:
        services.decide_join(services.request_to_join(unit, p), people[0], True)
    CouncilRules.objects.filter(unit=unit).update(decision_rule=rule, quorum=quorum)
    return unit, people


def decide(unit, people, votes):
    d = services.open_decision(people[0], unit, "Make more bread")
    for p, v in zip(people, votes, strict=False):
        services.vote(d, p, v)
    d.refresh_from_db()
    return d


def test_majority():
    unit, p = council()
    assert decide(unit, p, ["yes", "yes", "no"]).status == "approved"
    unit, p = council(tag="b")
    assert decide(unit, p, ["yes", "no", "no"]).status == "rejected"


def test_two_thirds():
    unit, p = council(rule="two_thirds")
    assert decide(unit, p, ["yes", "yes", "no"]).status == "approved"
    unit, p = council(4, rule="two_thirds", tag="b")
    assert decide(unit, p, ["yes", "yes", "no", "no"]).status == "rejected"


def test_consensus():
    unit, p = council(rule="consensus")
    assert decide(unit, p, ["yes", "abstain", "yes"]).status == "approved"
    unit, p = council(rule="consensus", tag="b")
    assert decide(unit, p, ["yes", "yes", "no"]).status == "rejected"


def test_a_failed_quorum_is_rejected_when_time_runs_out():
    unit, p = council(4, quorum="0.75")
    d = services.open_decision(p[0], unit, "x")
    services.vote(d, p[0], "yes")
    services.vote(d, p[1], "yes")
    assert services.close_due_decisions(timezone.now()) == 0  # still open
    assert services.close_due_decisions(timezone.now() + timedelta(days=4)) == 1
    d.refresh_from_db()
    assert d.status == "rejected" and d.result["reason"] == "quorum"


def test_a_non_council_member_cannot_vote():
    unit, p = council()
    d = services.open_decision(p[0], unit, "x")
    outsider = make_member("o@x.org", "Out")
    with pytest.raises(services.UnitError):
        services.vote(d, outsider, "yes")
    with pytest.raises(services.UnitError):
        services.open_decision(outsider, unit, "y")
    services.vote(d, p[0], "yes")
    with pytest.raises(services.UnitError):
        services.vote(d, p[0], "no")  # one vote each


def test_an_approved_rules_change_creates_the_next_version():
    unit, p = council()
    d = services.open_decision(p[0], unit, "Longer votes", kind="rules_change", payload={"vote_days": 7})
    for m in p:
        services.vote(d, m, "yes")
    assert council_rules.current(unit).version == 2
    assert council_rules.current(unit).vote_days == 7


def test_a_one_person_unit_needs_no_vote():
    unit = make_unit("solo")
    a = make_member()
    services.add_first_worker(unit, a)
    d = services.open_decision(a, unit, "Buy a mixer")
    assert d.status == "approved"


def test_pages(client):
    unit, p = council()
    client.force_login(p[0].user)
    r = client.post(reverse("units:decisions", args=[unit.slug]), {"title": "Hello", "kind": "other"})
    assert r.status_code == 302
    assert client.get(r["Location"]).status_code == 200
