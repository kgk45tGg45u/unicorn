"""Phase 11 acceptance: the first plan, then one plan year from proposals to the plan taking effect."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from freezegun import freeze_time

from apps.plan import jobs, services, variants
from apps.plan.check import check
from apps.plan.models import PlanPeriod
from apps.rules.models import ParameterChange
from apps.tickets.tests.conftest import pool
from apps.units.tests.conftest import make_member
from apps.votes import services as votes

pytestmark = pytest.mark.django_db
D = Decimal


def _vote_ranked(referendum, members, ballots):
    for member, ballot in zip(members, ballots, strict=False):
        votes.cast(referendum, member, ballot)


def test_hf16_a_plan_sets_only_plan_tier_defaults():
    from apps.plan import engine
    from apps.plan.defaults import plan_parameters

    assert plan_parameters()
    period = PlanPeriod.objects.create(starts_on=date(2027, 1, 1), ends_on=date(2027, 12, 31))
    from apps.plan.models import PlanVariant

    v = PlanVariant.objects.create(period=period, name="X", parameters={"plan.group_size": 20})
    assert any("not a default that a yearly plan may set" in i for i in engine.check_variant(v)["issues"])


def test_one_plan_year_from_the_first_plan_to_the_second_plans_start():
    with freeze_time("2026-01-10 10:00:00"):
        members = pool(25)
        first = services.start_first_plan()
    with freeze_time("2026-01-12 10:00:00"):
        votes.open_due_referendums()
    with freeze_time("2026-01-13 10:00:00"):
        for m in members[:10]:
            votes.cast(first.referendum, m, "yes")
    with freeze_time("2026-02-01 10:00:00"):
        votes.close_referendums()
        first.refresh_from_db()
        assert first.status == "running" and first.adopted_variant.is_default

    # July and August: three proposals
    with freeze_time("2026-07-15 10:00:00"):
        close = services.file_proposal(
            members[0], "close", "Close candle making", "Nobody buys them", {"trade_code": "C-9"}
        )
        focus = services.file_proposal(
            members[1], "focus", "Focus on repair", "We throw too much away", {"trade_code": "R-1"}
        )
        tool = services.file_proposal(
            members[2],
            "invest",
            "A new oven",
            "The old one is worn",
            {"trade_code": "B-10", "eur": "4000", "hours": "20"},
        )
        assert PlanPeriod.objects.filter(status="proposals").count() == 1

    # 1 September: the group of 9 is drawn
    with freeze_time("2026-09-01 10:00:00"):
        done = jobs.run(date(2026, 9, 1))
        assert done["group"] is True and jobs.run(date(2026, 9, 1)).get("group") is None  # safe to run twice
        period = PlanPeriod.objects.get(starts_on=date(2027, 1, 1))
        group = period.groups.get()
        assert group.seats.count() == 9 and period.status == "drafting"
        seat_members = [s.member for s in group.seats.all()]

    # Drafting: two variants that pass the engine check
    with freeze_time("2026-09-20 10:00:00"):
        a = variants.create_variant(seat_members[0], period, "Plan A")
        variants.include_proposal(a, close)
        variants.include_proposal(a, focus)
        variants.set_months(seat_members[0], a, [100] * 12, [2000] * 12)
        b = variants.copy_variant(seat_members[1], a, "Plan B")
        variants.set_parameter(seat_members[1], b, "economy.outside_sales_cap_share", 0.4)
        variants.include_proposal(b, tool)
        variants.submit_variant(seat_members[0], a)
        variants.submit_variant(seat_members[1], b)

    with freeze_time("2026-10-16 10:00:00"):
        assert jobs.run(date(2026, 10, 16))["drafting_closed"] is True
        period.refresh_from_db()
        assert period.status == "comments"

    # 1 November: the ranked vote opens; members rank
    with freeze_time("2026-11-01 10:00:00"):
        assert jobs.run(date(2026, 11, 1))["vote"] is True
        period.refresh_from_db()
        referendum = period.referendum
    with freeze_time("2026-11-03 10:00:00"):
        votes.open_due_referendums()
        referendum.refresh_from_db()
        ballots = [["Plan B", "Plan A"]] * 12 + [["Plan A", "Plan B"]] * 8
        _vote_ranked(referendum, members, ballots)
    with freeze_time("2026-11-20 10:00:00"):
        votes.close_referendums()
        period.refresh_from_db()
        assert period.status == "adopted" and period.adopted_variant.name == "Plan B"

    # 1 January: the plan's parameters apply, citing the referendum's ticket
    with freeze_time("2027-01-01 10:00:00"):
        jobs.run(date(2027, 1, 1))
        period.refresh_from_db()
        assert period.status == "running"
        assert (
            float(__import__("apps.rules.services", fromlist=["x"]).get_param("economy.outside_sales_cap_share")) == 0.4
        )
        change = ParameterChange.objects.get(parameter__key="economy.outside_sales_cap_share", decided_tier="plan")
        assert change.decided_by == referendum.ticket.number
        first.refresh_from_db()
        assert first.status == "closed"
        # the closure: opening a unit in the closed trade gives a red check
        assert check({"type": "open_unit", "kind": "production", "trade_code": "C-9"}).color == "red"
        assert make_member and D and timedelta
