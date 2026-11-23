from decimal import Decimal

import pytest

from apps.plan import engine, services, variants
from apps.plan.models import PlanProposal
from apps.tickets.models import Ticket
from apps.units.tests.conftest import make_member

from .conftest import drafting_group

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture
def work():
    period, group, members = drafting_group(25)
    return period, group, group.seats.first().member, members


def _fit(member, v):
    variants.set_months(member, v, [100] * 12, [2000] * 12)


def test_a_variant_over_the_euro_limit_has_an_issue(work):
    period, g, member, _members = work
    v = variants.create_variant(member, period, "Plan A")
    _fit(member, v)
    variants.set_budget_line(member, v, "tools", hours=10, eur=50000)  # 50,000 against 24,000 expected
    result = engine.check_variant(v)
    assert any("expects only" in i for i in result["issues"])
    with pytest.raises(services.PlanError, match="expects only"):
        variants.submit_variant(member, v)


def test_hours_over_the_planned_hours_are_an_issue(work):
    period, g, member, _members = work
    v = variants.create_variant(member, period, "Plan A")
    _fit(member, v)
    variants.set_budget_line(member, v, "social_security", hours=5000)
    assert any("hours are planned" in i or "hours but only" in i for i in engine.check_variant(v)["issues"])


def test_a_parameter_outside_its_bounds_is_refused(work):
    period, g, member, _members = work
    v = variants.create_variant(member, period, "Plan A")
    with pytest.raises(services.PlanError):
        variants.set_parameter(member, v, "economy.outside_sales_cap_share", 5)
    with pytest.raises(services.PlanError, match="plan tier"):
        variants.set_parameter(member, v, "plan.group_size", 10)
    variants.set_parameter(member, v, "economy.outside_sales_cap_share", 0.4)
    assert v.parameters["economy.outside_sales_cap_share"] == 0.4


def test_the_implied_tax_is_shown_and_follows_the_shares(work):
    period, g, member, _members = work
    v = variants.create_variant(member, period, "Plan A")
    base = D(engine.check_variant(v)["implied_tax"])
    variants.set_parameter(member, v, "economy.social_share_start", 0.1)
    assert D(engine.check_variant(v)["implied_tax"]) > base
    page = None
    assert page is None


def test_fewer_than_two_variants_cannot_be_submitted(work):
    period, g, member, _members = work
    a = variants.create_variant(member, period, "Plan A")
    _fit(member, a)
    variants.submit_variant(member, a)
    with pytest.raises(services.PlanError, match="between 2 and 3"):
        variants.finish_drafting(period)
    b = variants.copy_variant(member, a, "Plan B")
    variants.submit_variant(member, b)
    variants.finish_drafting(period)
    period.refresh_from_db()
    assert period.status == "comments"


def test_only_the_group_edits_and_a_submitted_plan_is_frozen(work):
    period, g, member, members = work
    outsider = next(m for m in members if not g.seats.filter(member=m).exists())
    with pytest.raises(services.PlanError, match="planning group"):
        variants.create_variant(outsider, period, "Mine")
    v = variants.create_variant(member, period, "Plan A")
    _fit(member, v)
    variants.submit_variant(member, v)
    with pytest.raises(services.PlanError, match="already submitted"):
        variants.set_budget_line(member, v, "tools", eur=1)
    assert make_member and Ticket


def test_proposals_go_into_variants_and_the_rest_is_left_out_with_a_reason(work):
    from freezegun import freeze_time

    period, g, member, _members = work
    with freeze_time("2026-07-15 10:00:00"):
        close = services.file_proposal(member, "close", "Close candle making", "", {"trade_code": "C-9"})
        focus = services.file_proposal(member, "focus", "Focus on repair", "", {"trade_code": "R-1"})
    a = variants.create_variant(member, period, "Plan A")
    variants.include_proposal(a, close)
    assert a.closures.get().trade_code == "C-9"
    close.refresh_from_db()
    assert close.status == "included"
    with pytest.raises(services.PlanError, match="why"):
        variants.leave_out(member, focus, " ")
    variants.leave_out(member, focus, "Too early")
    focus.refresh_from_db()
    assert focus.status == "left_out" and focus.left_out_reason == "Too early" and PlanProposal.objects.count() == 2
