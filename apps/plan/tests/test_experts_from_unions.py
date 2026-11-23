import pytest

from apps.bodies import experts, services
from apps.bodies.models import ExpertNomination
from apps.bodies.tests.conftest import active_union
from apps.plan import group
from apps.plan import services as plan_services
from apps.plan.models import ExpertAdviser, GroupDecision
from apps.rules.models import Parameter

from .conftest import drafting_group

pytestmark = pytest.mark.django_db


def _group_today(n=25):
    today = plan_services.today()
    period, g, members = drafting_group(n, year=today.year + 1, on=today)
    return g, members


def _outsiders(g, members, k):
    seats = set(g.seats.values_list("member_id", flat=True))
    return [m for m in members if m.pk not in seats][:k]


def _name(union, people, solo_member, nominee, statement="Thirty years of joinery"):
    decision = services.open_decision(
        people[0],
        union,
        f"Name {nominee.number}",
        kind="nominate_expert",
        payload={"member": nominee.number, "statement": statement},
    )
    services.vote(decision, people[0], "yes")
    services.vote(decision, solo_member, "yes")
    decision.refresh_from_db()
    return decision


def _approve_in_group(g, adviser):
    seats = [s.member for s in g.seats.all()]
    d = group.propose_adviser(g, seats[0], adviser)
    for member in seats:
        d = GroupDecision.objects.get(pk=d.pk)
        if d.status == "open":
            group.vote(d, member, True)
    return GroupDecision.objects.get(pk=d.pk)


def test_a_union_nomination_reaches_the_group():
    union, crew, people, solo, solo_member = active_union()
    g, members = _group_today()
    nominee = _outsiders(g, members, 1)[0]
    decision = _name(union, people, solo_member, nominee)
    nomination = ExpertNomination.objects.get(decision=decision)
    assert nomination.status == "pending" and not ExpertAdviser.objects.filter(group=g).exists()
    adviser = experts.accept(nomination, nominee)
    assert adviser.nominated_by_union == union and adviser.statement == "Thirty years of joinery"
    assert not adviser.approved  # the group still decides
    assert _approve_in_group(g, adviser).status == "approved"
    assert ExpertAdviser.objects.get(pk=adviser.pk).approved


def test_the_member_can_decline_and_only_the_named_member_can_answer():
    union, crew, people, solo, solo_member = active_union()
    g, members = _group_today()
    nominee, other = _outsiders(g, members, 2)
    nomination = ExpertNomination.objects.get(decision=_name(union, people, solo_member, nominee))
    with pytest.raises(services.BodyError, match="not waiting for your answer"):
        experts.accept(nomination, other)
    experts.decline(nomination, nominee)
    nomination.refresh_from_db()
    assert nomination.status == "declined" and not ExpertAdviser.objects.exists()
    with pytest.raises(services.BodyError, match="not waiting"):
        experts.accept(nomination, nominee)


def test_the_limit_of_experts_max_holds():
    union, crew, people, solo, solo_member = active_union()
    Parameter.objects.filter(key="plan.experts_max").update(value=1)
    g, members = _group_today()
    first, second = _outsiders(g, members, 2)
    advisers = []
    for nominee in (first, second):
        nomination = ExpertNomination.objects.get(decision=_name(union, people, solo_member, nominee))
        advisers.append(experts.accept(nomination, nominee))
    assert _approve_in_group(g, advisers[0]).status == "approved"
    assert _approve_in_group(g, advisers[1]).status == "rejected"
    assert g.advisers.filter(approved=True).count() == 1


def test_an_advisers_vote_in_the_group_is_refused():
    union, crew, people, solo, solo_member = active_union()
    g, members = _group_today()
    nominee = _outsiders(g, members, 1)[0]
    adviser = experts.accept(ExpertNomination.objects.get(decision=_name(union, people, solo_member, nominee)), nominee)
    d = group.propose_adviser(g, g.seats.first().member, adviser)
    with pytest.raises(plan_services.PlanError, match="Only members of the planning group"):
        group.vote(d, nominee, True)


def test_a_seat_of_the_group_cannot_be_nominated_and_a_late_nomination_is_refused():
    union, crew, people, solo, solo_member = active_union()
    g, members = _group_today()
    seat_member = g.seats.first().member
    with pytest.raises(services.BodyError, match="cannot also be"):
        services.open_decision(
            people[0], union, "Name a seat", kind="nominate_expert", payload={"member": seat_member.number}
        )
    with pytest.raises(services.BodyError, match="verified member"):
        services.open_decision(
            people[0], union, "Name nobody", kind="nominate_expert", payload={"member": "M-0000-0000"}
        )
    nominee = _outsiders(g, members, 1)[0]
    nomination = ExpertNomination.objects.get(decision=_name(union, people, solo_member, nominee))
    from datetime import timedelta

    with pytest.raises(services.BodyError, match="time to offer"):
        experts.accept(nomination, nominee, on=plan_services.today() + timedelta(days=30))


def test_volunteers_can_still_offer_to_advise_once_unions_exist():
    union, crew, people, solo, solo_member = active_union()
    g, members = _group_today()
    volunteer = _outsiders(g, members, 1)[0]
    adviser = group.volunteer_adviser(volunteer, g, "I know bread")
    assert adviser.nominated_by_union is None
