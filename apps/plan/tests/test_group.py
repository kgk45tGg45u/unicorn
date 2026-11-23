from datetime import date, timedelta

import pytest

from apps.plan import defaults, group, services
from apps.plan.models import ExpertAdviser, GroupDecision, GroupSeat
from apps.tickets import draw
from apps.tickets.tests.conftest import pool
from apps.units.models import HoursEntry
from apps.units.tests.conftest import make_member

from .conftest import drafting_group, new_period

pytestmark = pytest.mark.django_db


def test_the_size_rule_for_25_and_for_1000_members():
    assert group.group_size(25) == 9
    assert group.group_size(1000) == 15
    assert group.group_size(45) == 15 and group.group_size(10) == 5


def test_a_group_of_nine_is_drawn_from_25_members_and_the_draw_can_be_repeated():
    period, g, members = drafting_group(25)
    assert g.seats.count() == 9
    c = g.confirmation
    numbers = sorted(m.number for m in draw.eligible(g.ticket, "confirmers"))
    assert draw.reproduce(c, numbers) == [s.member.number for s in g.seats.order_by("drawn_order")]


def test_last_years_members_are_excluded():
    period, first, members = drafting_group(25, year=2027)
    second_period = new_period(2028, "drafting")
    defaults.build_default_variant(second_period)
    second = group.draw_group(second_period, on=date(2027, 9, 1))
    assert not set(first.seats.values_list("member_id", flat=True)) & set(
        second.seats.values_list("member_id", flat=True)
    )


def test_a_decliner_is_replaced_and_silence_counts_as_declining():
    period, g, members = drafting_group(25)
    seat = g.seats.first()
    group.answer(seat, False)
    assert group.active_seats(g).count() == 9 and g.seats.count() == 10
    with pytest.raises(services.PlanError, match="already"):
        group.answer(seat, True)
    assert group.expire_unanswered(on=date(2026, 9, 20)) == 9  # every silent seat is replaced
    assert g.seats.count() == 19


def test_an_advisers_vote_is_refused_and_advisers_are_limited():
    period, g, members = drafting_group(25)
    outsider = next(m for m in members if not g.seats.filter(member=m).exists())
    adviser = group.volunteer_adviser(outsider, g, "I know bread", on=date(2026, 9, 5))
    seat_member = g.seats.first().member
    d = group.propose_adviser(g, seat_member, adviser)
    with pytest.raises(services.PlanError, match="Only members of the planning group"):
        group.vote(d, outsider, True)
    for s in list(g.seats.all())[:5]:
        d = GroupDecision.objects.get(pk=d.pk)
        if d.status == "open":
            group.vote(d, s.member, True)
    assert ExpertAdviser.objects.get(pk=adviser.pk).approved
    with pytest.raises(services.PlanError, match="time to offer"):
        group.volunteer_adviser(make_member("late@x.org", "Late"), g, "x", on=date(2026, 10, 1))
    with pytest.raises(services.PlanError, match="cannot also be"):
        group.volunteer_adviser(seat_member, g, "x", on=date(2026, 9, 5))


def test_hours_above_the_weekly_cap_are_not_approved():
    period, g, members = drafting_group(25)
    member = g.seats.first().member
    entry, cut = group.record_hours(member, g, 300)  # 5 of the 6 hours
    assert cut == 0 and entry.status == "paid"
    entry2, cut2 = group.record_hours(member, g, 120)  # only 60 minutes remain
    assert cut2 == 60 and entry2.minutes == 60
    with pytest.raises(services.PlanError, match="limit"):
        group.record_hours(member, g, 10)
    assert HoursEntry.objects.filter(ref_type="planning_group").count() == 2
    outsider = make_member("o@x.org", "Outsider")
    with pytest.raises(services.PlanError):
        group.record_hours(outsider, g, 10)
    assert timedelta(0) == timedelta(0) and pool and GroupSeat
