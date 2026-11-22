from datetime import timedelta

import pytest

from apps.members import services as ms
from apps.units import services
from apps.units.models import Responsibility

from .conftest import make_member, make_unit

pytestmark = pytest.mark.django_db


def council(n=3):
    unit = make_unit()
    people = [make_member(f"m{i}@x.org", f"M{i}") for i in range(n)]
    services.add_first_worker(unit, people[0])
    for p in people[1:]:
        services.decide_join(services.request_to_join(unit, p), people[0], True)
    return unit, people


def age(unit, days):
    r = services.responsible(unit)
    r.starts_at -= timedelta(days=days)
    r.save()


def test_the_creator_is_the_first_responsible():
    unit, p = council()
    r = services.responsible(unit)
    assert (r.member, r.how) == (p[0], "founder")
    assert services.can_edit_unit(p[1], unit)
    assert not services.can_edit_unit(make_member("z@x.org", "Zed"), unit)


def test_rotation_after_six_months_picks_the_member_with_the_fewest_days():
    unit, p = council()
    age(unit, 200)
    assert services.rotate_due() == 1
    first = services.responsible(unit)
    assert first.member == p[1]  # p[2] and p[1] have 0 days; p[1] joined first
    assert first.how == "rotation"
    assert services.rotate_due() == 0  # not due again
    age(unit, 200)
    services.rotate_due()
    assert services.responsible(unit).member == p[2]
    age(unit, 200)
    services.rotate_due()
    assert services.responsible(unit).member == p[0]  # equal days: the earliest joined


def test_not_rotated_before_the_time():
    unit, p = council()
    age(unit, 100)
    assert services.rotate_due() == 0
    assert services.responsible(unit).member == p[0]


def test_declining_passes_the_turn_on():
    unit, p = council()
    age(unit, 200)
    services.rotate_due()
    assert services.responsible(unit).member == p[1]
    services.decline_turn(p[1], unit)
    assert services.responsible(unit).member == p[2]
    assert p[1].pk in services.responsible(unit).declined_by
    with pytest.raises(services.UnitError):
        services.decline_turn(p[1], unit)  # no longer the responsible


def test_declining_when_everybody_declines_still_leaves_a_responsible():
    unit, p = council(2)
    services.decline_turn(p[0], unit)
    assert services.responsible(unit).member == p[1]
    services.decline_turn(p[1], unit)
    assert services.responsible(unit) is not None


def test_leaving_the_unit_hands_over():
    unit, p = council()
    services.leave_unit(p[0], unit)
    r = services.responsible(unit)
    assert r.member == p[1] and r.how == "handover"
    assert Responsibility.objects.filter(unit=unit, ends_at__isnull=True).count() == 1


def test_leaving_unicorn_hands_over_instead_of_blocking():
    unit, p = council()
    ms.leave(p[0])
    assert services.responsible(unit).member == p[1]
    assert not services.is_worker(p[0], unit)
