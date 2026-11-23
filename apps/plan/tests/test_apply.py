from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.catalogue import services as cat
from apps.plan import apply, services
from apps.plan.models import ClosureItem, GroupSeat, PlanningGroup
from apps.rules.models import Parameter, ParameterChange
from apps.rules.services import get_param
from apps.tickets import actions
from apps.tickets.models import Ticket
from apps.tickets.tests.conftest import pool
from apps.units import services as unit_services
from apps.units.tests.conftest import make_member, make_unit
from apps.votes import services as votes

from .conftest import running_plan

pytestmark = pytest.mark.django_db


def test_applying_sets_the_parameters_with_the_plan_tier_and_the_referendum_ticket():
    members = pool(5)
    period = services.start_first_plan()
    default = period.variants.get()
    default.parameters = {**default.parameters, "economy.outside_sales_cap_share": 0.4}
    default.save()
    votes.open_due_referendums(now=timezone.now() + timedelta(days=2))
    period.referendum.refresh_from_db()
    for m in members[:4]:
        votes.cast(period.referendum, m, "yes")
    votes.close_referendums(now=timezone.now() + timedelta(days=40))
    assert float(get_param("economy.outside_sales_cap_share")) == 0.4
    change = ParameterChange.objects.get(parameter__key="economy.outside_sales_cap_share", decided_tier="plan")
    assert change.decided_tier == "plan" and change.decided_by == period.referendum.ticket.number
    assert "Yearly plan" in change.reason


def test_a_closure_item_closes_its_unit_after_the_hearing():
    period, variant = running_plan()
    unit = make_unit("candles")
    worker = make_member("w@x.org", "Worker")
    unit_services.add_first_worker(unit, worker)
    item = cat.create_item("Candle", "product", "pc")
    offer = cat.create_offer(worker, unit, item, batch_size=10, cycle_days=1, direct_minutes_per_batch=60)
    cat.publish_offer(offer, worker)
    today = date.today()
    ClosureItem.objects.create(variant=variant, unit=unit, from_date=today, hearing_until=today - timedelta(days=5))
    assert apply.run_closures(on=today) >= 1
    unit.refresh_from_db()
    offer.refresh_from_db()
    assert unit.status == "closing" and offer.status == "retired"
    assert Ticket.objects.filter(type="plan_hearing", scope_unit=unit).exists()
    assert apply.finish_closing_units() == 1
    unit.refresh_from_db()
    assert unit.status == "closed"


def test_the_hearing_opens_thirty_days_before_the_end():
    period, variant = running_plan()
    unit = make_unit("wax")
    today = date.today()
    ClosureItem.objects.create(
        variant=variant, unit=unit, from_date=today + timedelta(days=90), hearing_until=today + timedelta(days=45)
    )
    assert apply.run_closures(on=today) == 0
    assert apply.run_closures(on=today + timedelta(days=15)) == 1
    unit.refresh_from_db()
    assert unit.status != "closing"  # the hearing is open, the unit still works


def test_an_emergency_change_needs_the_red_light(monkeypatch):
    period, variant = running_plan()
    member = pool(1)[0]
    group = PlanningGroup.objects.create(
        period=period,
        ticket=Ticket.objects.create(
            number="T-GRP", type="plan_group", title="g", decision_method="none", status="done"
        ),
    )
    GroupSeat.objects.create(group=group, member=member, drawn_order=1)
    changes = {"economy.outside_sales_cap_share": 0.3}
    with pytest.raises(services.PlanError, match="red warning light"):
        apply.propose_emergency(member, changes, "The shelves are empty")
    monkeypatch.setattr(apply, "red_months", lambda: 2)
    with pytest.raises(services.PlanError, match="plan tier"):
        apply.propose_emergency(member, {"plan.group_size": 9}, "x")
    ticket = apply.propose_emergency(member, changes, "The shelves are empty")
    assert ticket.type == "plan_emergency"
    actions.approve(ticket, how="confirmers")
    assert float(get_param("economy.outside_sales_cap_share")) == 0.3
    assert ParameterChange.objects.filter(decided_by=ticket.number, decided_tier="plan").exists()
    assert Parameter and make_member
