from datetime import date
from decimal import Decimal

import pytest
from freezegun import freeze_time

from apps.market import services
from apps.market.models import OrderLine, ProductionOrder, WeeklyPlan
from apps.market.tests.conftest import World
from apps.units.models import HoursEntry
from apps.units.tests.conftest import make_member

pytestmark = pytest.mark.django_db
D = Decimal
WEDNESDAY = "2026-06-10 10:00:00"


def test_two_orders_for_the_same_offer_share_one_batch(world):
    a, b = world.buyer("a@x.org"), world.buyer("b@x.org")
    first = services.place_order(a, world.bread, D(2))
    second = services.place_order(b, world.bread, D(3))
    assert first.production_order_id == second.production_order_id
    po = first.production_order
    assert po.quantity == 5 and po.quantity_assigned == 5 and po.status == "open"
    assert first.status == second.status == OrderLine.IN_PRODUCTION


def test_a_full_batch_is_not_shared(world):
    a = world.buyer("a@x.org", uniq=20)
    first = services.place_order(a, world.bread, D(40))  # exactly one batch of 40
    second = services.place_order(a, world.bread, D(1))
    assert first.production_order_id != second.production_order_id


@freeze_time(WEDNESDAY)
def test_a_continuous_unit_fills_its_weekly_plan():
    w = World(mode="continuous")
    services.set_weekly_plan(w.baker, w.bread, 10, "The week's usual baking")
    plan = WeeklyPlan.objects.get()
    assert plan.quantity_per_week == 10 and plan.set_by.status == "approved"
    a, b, c = (w.buyer(f"{n}@x.org") for n in "abc")
    first = services.place_order(a, w.bread, D(6))
    second = services.place_order(b, w.bread, D(4))
    third = services.place_order(c, w.bread, D(1))
    assert first.production_order_id == second.production_order_id
    po = first.production_order
    # lead time: 1 day to bake, 1 for the flour, 7 for the salt bought outside: ready on 19 June, in the week of 15 June
    assert po.week_start == date(2026, 6, 15) and po.quantity == 10 and po.quantity_assigned == 10
    assert po.due_date == date(2026, 6, 21) and first.due_date == date(2026, 6, 21)
    assert third.production_order.week_start == date(2026, 6, 22)  # that week is full: the next week's order
    assert third.due_date == date(2026, 6, 28)


def test_a_weekly_plan_needs_a_continuous_unit_and_a_reason(world):
    with pytest.raises(services.MarketError, match="continuous"):
        services.set_weekly_plan(world.baker, world.bread, 10, "why")
    world.bakery_unit.mode = "continuous"
    world.bakery_unit.save()
    w = world
    with pytest.raises(services.MarketError, match="why"):
        services.set_weekly_plan(w.baker, w.bread, 10, " ")


def test_starting_a_batch_blocks_free_cancellation(world):
    buyer = world.buyer()
    line = services.place_order(buyer, world.bread, D(2))
    services.start_production(line.production_order, world.baker)
    with pytest.raises(services.MarketError, match="already being made"):
        services.cancel_line(line, buyer)
    line.refresh_from_db()
    assert line.status == OrderLine.IN_PRODUCTION and line.hold.status == "active"


def test_cancelling_before_the_start_shrinks_or_cancels_the_batch(world):
    a, b = world.buyer("a@x.org"), world.buyer("b@x.org")
    first = services.place_order(a, world.bread, D(2))
    second = services.place_order(b, world.bread, D(3))
    po = first.production_order
    services.cancel_line(first, a)
    po.refresh_from_db()
    assert po.quantity == 3 and po.quantity_assigned == 3 and po.status == "open"
    services.cancel_line(second, b)
    po.refresh_from_db()
    assert po.status == "cancelled"


def test_only_a_worker_of_the_unit_starts_or_completes_a_batch(world):
    line = services.place_order(world.buyer(), world.bread, D(2))
    stranger = make_member("s@x.org", "Stranger")
    with pytest.raises(services.MarketError, match="work in this unit"):
        services.start_production(line.production_order, stranger)
    with pytest.raises(services.MarketError, match="Start the batch first"):
        services.complete_production(line.production_order, world.baker, 2)


def test_completing_serves_the_lines_in_the_order_placed(world):
    a, b = world.buyer("a@x.org"), world.buyer("b@x.org")
    first = services.place_order(a, world.bread, D(2))
    second = services.place_order(b, world.bread, D(3))
    po = first.production_order
    services.start_production(po, world.baker)
    services.complete_production(po, world.baker, 5)
    po.refresh_from_db()
    first.refresh_from_db(), second.refresh_from_db()
    assert po.status == "done" and po.quantity_done == 5
    assert first.status == second.status == OrderLine.READY


def test_a_short_batch_serves_the_first_orders_and_moves_the_rest_on(world):
    a, b = world.buyer("a@x.org"), world.buyer("b@x.org")
    first = services.place_order(a, world.bread, D(2))
    second = services.place_order(b, world.bread, D(3))
    po = first.production_order
    services.start_production(po, world.baker)
    services.complete_production(po, world.baker, 4)  # 2 are served, the order for 3 does not fit
    first.refresh_from_db(), second.refresh_from_db()
    assert first.status == OrderLine.READY
    assert second.status == OrderLine.IN_PRODUCTION and second.production_order_id != po.pk
    assert second.production_order.status == "open" and second.production_order.quantity_assigned == 3


def test_workers_record_hours_on_the_production_order(world):
    line = services.place_order(world.buyer(), world.bread, D(2))
    po = line.production_order
    entry = services.record_production_hours(world.baker, po, date.today(), 90)
    assert (entry.activity, entry.ref_type, entry.ref_id) == ("order", "production_order", str(po.pk))
    assert HoursEntry.objects.get().status == "paid"  # a one-person unit approves at once
    with pytest.raises(services.MarketError):
        services.record_production_hours(make_member("s@x.org", "S"), po, date.today(), 30)


def test_a_batch_that_nobody_started_can_be_cancelled_by_the_plan_only(world):
    # an order places exactly one open production order per partly filled batch
    services.place_order(world.buyer(), world.bread, D(2))
    assert ProductionOrder.objects.filter(status="open").count() == 1
