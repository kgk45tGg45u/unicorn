from datetime import timedelta

import pytest
from django.utils import timezone

from apps.bodies import services
from apps.bodies.models import UnionDelegate, UnionRules
from apps.units import services as unit_services
from apps.units.models import Unit

from .conftest import active_union

pytestmark = pytest.mark.django_db


def test_the_first_delegate_is_the_responsible_and_a_solo_member_speaks_for_their_unit():
    union, crew, people, solo, solo_member = active_union()
    assert services.current_delegate(union, crew).member == people[0]
    assert services.current_delegate(union, crew).how == "first"
    assert services.current_delegate(union, solo).member == solo_member


def test_delegates_rotate_after_six_months():
    union, crew, people, solo, solo_member = active_union()
    jobs_now = timezone.now()
    assert services.rotate_delegates(jobs_now + timedelta(days=100)) == 0
    assert services.rotate_delegates(jobs_now + timedelta(days=200)) == 1  # the solo unit keeps its only member
    new = services.current_delegate(union, crew)
    assert new.member != people[0] and new.how == "rotation"
    assert services.current_delegate(union, solo).member == solo_member
    assert UnionDelegate.objects.filter(union=union, unit=crew, ends_at__isnull=False).count() == 1


def test_a_delegate_who_leaves_the_unit_hands_the_role_over_at_once():
    union, crew, people, solo, solo_member = active_union()
    unit_services.leave_unit(people[0], crew)
    new = services.current_delegate(union, crew)
    assert new is not None and new.member != people[0] and new.how == "handover"


def test_a_delegate_can_decline_a_turn():
    union, crew, people, solo, solo_member = active_union()
    row = services.decline_delegate_turn(people[0], union, crew)
    assert row.member != people[0] and people[0].pk in row.declined_by
    with pytest.raises(services.BodyError, match="not the delegate"):
        services.decline_delegate_turn(people[0], union, crew)


def test_one_vote_per_member_unit():
    union, crew, people, solo, solo_member = active_union()
    decision = services.open_decision(people[0], union, "A standard for oak", kind="other")
    services.vote(decision, people[0], "yes")
    with pytest.raises(services.BodyError, match="already voted"):
        services.vote(decision, people[0], "no")
    with pytest.raises(services.BodyError, match="Only the delegates"):
        services.vote(decision, people[1], "yes")  # a council member who is not the delegate
    services.vote(decision, solo_member, "yes")
    decision.refresh_from_db()
    assert decision.status == "approved" and decision.result["yes"] == 2


def test_only_delegates_open_decisions():
    union, crew, people, solo, solo_member = active_union()
    with pytest.raises(services.BodyError, match="Only the delegates"):
        services.open_decision(people[1], union, "x")


def test_a_decision_without_enough_votes_is_rejected_when_time_runs_out():
    union, crew, people, solo, solo_member = active_union()
    decision = services.open_decision(people[0], union, "A standard", kind="other")
    assert services.close_due_decisions(timezone.now()) == 0
    assert services.close_due_decisions(timezone.now() + timedelta(days=10)) == 1
    decision.refresh_from_db()
    assert decision.status == "rejected" and decision.result["reason"] == "quorum"


def test_the_union_changes_only_its_own_rules():
    union, crew, people, solo, solo_member = active_union()
    decision = services.open_decision(
        people[0], union, "Two thirds from now on", kind="rules_change", payload={"decision_rule": "two_thirds"}
    )
    services.vote(decision, people[0], "yes")
    services.vote(decision, solo_member, "yes")
    rules = services.current_rules(union)
    assert rules.version == 2 and rules.decision_rule == "two_thirds" and rules.adopted_by_id == decision.pk
    assert UnionRules.objects.filter(union=union).count() == 2
    with pytest.raises(services.BodyError, match="pay"):
        services.open_decision(
            people[0],
            union,
            "Bonus",
            kind="rules_change",
            payload={"clauses_md": "Members who pay extra uniq per hour get a bonus."},
        )


def test_hf20_union_decision_cannot_touch_a_unit():
    union, crew, people, solo, solo_member = active_union()
    for action in ("close_unit", "change_unit", "set_parameter", "approve_hours", "change_council_rules"):
        with pytest.raises(services.BodyError, match="cannot do this"):
            services.open_decision(
                people[0], union, "Close the crew", kind="other", payload={"action": action, "unit_id": crew.pk}
            )
    with pytest.raises(services.BodyError, match="may not do this"):
        services.register_action("close_unit", lambda decision: None)
    assert Unit.objects.get(pk=crew.pk).status == "open"


def test_hf20_the_allow_list_is_checked_again_when_the_action_runs():
    union, crew, people, solo, solo_member = active_union()
    decision = services.open_decision(people[0], union, "A standard", kind="other")
    decision.payload = {"action": "close_unit", "unit_id": crew.pk}  # changed behind the service's back
    decision.save(update_fields=["payload"])
    services.vote(decision, people[0], "yes")
    with pytest.raises(services.BodyError, match="cannot do this"):
        services.vote(decision, solo_member, "yes")  # the last vote closes it and runs the action
    assert Unit.objects.get(pk=crew.pk).status == "open"
