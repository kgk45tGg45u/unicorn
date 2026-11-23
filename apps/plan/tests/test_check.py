from decimal import Decimal

import pytest

from apps.catalogue import services as cat
from apps.core.models import AuditEvent
from apps.plan.check import CheckPoint, CheckResult, check
from apps.tradefund import allocation
from apps.units.tests.conftest import make_member

from .conftest import running_plan

pytestmark = pytest.mark.django_db
D = Decimal


def test_without_a_running_plan_the_stub_stays_green():
    assert check({"type": "open_unit"}).color == "green"


def test_worst_colour_wins():
    assert CheckResult([CheckPoint("green", "a"), CheckPoint("amber", "b")]).color == "amber"
    assert CheckResult([CheckPoint("amber", "b"), CheckPoint("red", "c")]).color == "red"


def test_a_closure_list_trade_is_red():
    running_plan(closures=["B-10"])
    result = check({"type": "open_unit", "kind": "production", "trade_code": "B-10"})
    assert result.color == "red" and any("closes" in p.text for p in result.points)
    assert check({"type": "open_unit", "trade_code": "X-99"}).color == "green"


def test_a_request_beyond_its_budget_line_is_red():
    running_plan(budget=[("tools", "", 0, 1000)])
    result = check({"type": "purchase", "amount_eur": "5000"})
    assert result.color == "red" and any("left" in p.text for p in result.points)
    assert check({"type": "purchase", "amount_eur": "300"}).color == "green"


def test_a_request_that_fits_with_a_low_reserve_is_amber(monkeypatch):
    running_plan(budget=[("tools", "", 0, 1000)])
    monkeypatch.setattr(allocation, "reserve_months", lambda *a, **k: D("2.0"))
    from apps.rules.services import get_param

    assert (
        D(str(get_param("alarms.euro_reserve_red_months")))
        <= D("2.0")
        < D(str(get_param("alarms.euro_reserve_amber_months")))
    )
    assert check({"type": "purchase", "amount_eur": "300"}).color == "amber"


def test_a_focus_trade_gets_a_green_point():
    running_plan(focus=["F-20"])
    result = check({"type": "open_unit", "trade_code": "F-20"})
    assert any("focus" in p.text for p in result.points) and result.color == "green"


def test_a_service_without_visible_demand_is_amber():
    running_plan()
    result = check({"type": "open_unit", "kind": "service", "name": "Haircut"})
    assert any("No visible demand" in p.text for p in result.points) and result.color == "amber"


def test_hf15_check_never_rejects_and_changes_nothing():
    running_plan(budget=[("tools", "", 0, 10)], closures=["B-10"])
    before = AuditEvent.objects.count()
    for request in ({}, {"type": "purchase", "amount_eur": "x1"}, {"offer": 999999}, {"item": "nope"}):
        try:
            result = check(request)
        except (ValueError, TypeError, Exception) as e:  # noqa: BLE001
            pytest.fail(f"the check raised for {request}: {e!r}")
        assert result.color in ("green", "amber", "red")
    assert AuditEvent.objects.count() == before
    assert make_member and cat
