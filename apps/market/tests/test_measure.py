from datetime import date, timedelta
from decimal import Decimal

import pytest
from freezegun import freeze_time

from apps.catalogue import services as cat
from apps.catalogue.models import Offer
from apps.core.models import AuditEvent
from apps.market import measure, services
from apps.market.models import InputRequest, PlausibilityRecord, ProductionOrder
from apps.market.tests.conftest import World
from apps.units import services as us

pytestmark = pytest.mark.django_db
D = Decimal


def deliver(world, quantity, email="buyer@x.org"):
    """An order that is made, handed over and confirmed. Returns the production order."""
    buyer = world.buyer(email, uniq=50)
    line = services.place_order(buyer, world.bread, D(quantity))
    po = line.production_order
    services.start_production(po, world.baker)
    services.complete_production(po, world.baker, quantity)
    services.hand_over(line, world.baker)
    services.confirm_received(line, buyer)
    return po


def hours(world, po, minutes, days_ago=0):
    return services.record_production_hours(world.baker, po, services.today() - timedelta(days=days_ago), minutes)


def test_measured_hours_replace_declared_hours_after_the_thresholds(world):
    po = deliver(world, 20)
    for week in range(4):
        hours(world, po, 540, days_ago=7 * week)  # 36 hours in four weeks
    hours(world, po, 180, days_ago=28)  # 39 hours in all
    assert measure.measured_hours(world.bread) is None  # fewer than 40 hours
    hours(world, po, 60, days_ago=35)  # 40 hours
    assert measure.measured_hours(world.bread) == D("2.0000")  # 40 hours for 20 loaves
    assert world.bread.value_basis == "declared"

    cat.recompute_values()
    world.bread.refresh_from_db()
    assert world.bread.measured_hours_per_unit == D("2.0000") and world.bread.value_basis == "measured"
    assert world.bread.value_direct == D("2.0000")
    # the price of new orders follows; an order placed before keeps its price (HF-3)
    assert world.bread.value_total > D("2.0")


def test_too_few_units_keep_the_declared_hours(world):
    po = deliver(world, 9)
    for week in range(6):
        hours(world, po, 540, days_ago=7 * week)  # many hours, but only 9 loaves
    assert measure.measured_hours(world.bread) is None


def test_old_hours_and_deliveries_fall_out_of_the_window(world):
    po = deliver(world, 20)
    for week in range(5):
        hours(world, po, 540, days_ago=7 * week)
    assert measure.measured_hours(world.bread) is not None
    with freeze_time(services.timezone.now() + timedelta(days=120)):
        assert measure.measured_hours(world.bread) is None


def test_the_supply_weights_follow_the_deliveries(world):
    from apps.market.tests.conftest import unit_for
    from apps.units.tests.conftest import make_member

    rival = make_member("rival@x.org", "Rival")
    rival_offer = cat.create_offer(
        rival, unit_for(rival, "mill-two"), world.mill.item, batch_size=D(100), direct_minutes_per_batch=300
    )
    cat.publish_offer(rival_offer, rival)
    by_item = {world.mill.item_id: [world.mill, rival_offer]}
    assert measure.supply_weights(by_item)[world.mill.item_id] == {world.mill.pk: 0.5, rival_offer.pk: 0.5}

    po = ProductionOrder.objects.create(offer=world.bread, quantity=1, due_date=services.today())
    for offer, quantity in ((world.mill, 30), (rival_offer, 10)):
        InputRequest.objects.create(
            production_order=po,
            item=offer.item,
            quantity=quantity,
            source="unicorn",
            supplier_offer=offer,
            status="delivered",
            delivered_at=services.timezone.now(),
            due_date=services.today(),
        )
    weights = measure.supply_weights(by_item)[world.mill.item_id]
    assert weights[world.mill.pk] == pytest.approx(0.75) and weights[rival_offer.pk] == pytest.approx(0.25)
    assert cat.SUPPLY_WEIGHTS_HOOK is measure.supply_weights
    cat.recompute_values()  # the engine accepts them
    assert Offer.objects.get(pk=world.bread.pk).value_total > 0


def make_month(world, day, units=20, minutes=189, email="b@x.org"):
    with freeze_time(day):
        po = deliver(world, units, email)
        hours(world, po, minutes)


def test_a_40_percent_hours_gap_for_2_months_creates_a_notice():
    with freeze_time("2026-02-20 12:00:00"):
        world = World()
    # 20 loaves a month should take 20 x 0.1125 = 2.25 hours: 3.15 hours is 40% more
    make_month(world, "2026-03-10 12:00:00", email="march@x.org")
    make_month(world, "2026-04-10 12:00:00", email="april@x.org")
    with freeze_time("2026-05-02 12:00:00"):
        measure.run_plausibility(date(2026, 3, 1))
        assert not AuditEvent.objects.filter(verb="plausibility.hours_gap").exists()  # one month is not enough
        measure.run_plausibility(date(2026, 4, 1))
        measure.run_plausibility(date(2026, 4, 1))  # safe to run twice
    notices = AuditEvent.objects.filter(verb="plausibility.hours_gap")
    assert notices.count() == 1
    assert notices.get().data["month"] == "2026-04"
    record = PlausibilityRecord.objects.get(month=date(2026, 4, 1), kind="hours")
    assert record.flagged and record.value == D("0.4000") and record.notified


def test_a_small_gap_or_a_broken_streak_makes_no_notice():
    with freeze_time("2026-02-20 12:00:00"):
        world = World()
    make_month(world, "2026-03-10 12:00:00", minutes=189, email="a@x.org")  # 40% over
    make_month(world, "2026-04-10 12:00:00", minutes=135, email="b@x.org")  # exactly the declared hours
    make_month(world, "2026-05-10 12:00:00", minutes=189, email="c@x.org")  # 40% over again
    with freeze_time("2026-06-02 12:00:00"):
        for month in (3, 4, 5):
            measure.run_plausibility(date(2026, month, 1))
    assert not AuditEvent.objects.filter(verb="plausibility.hours_gap").exists()


def test_inputs_far_above_what_the_output_needs_make_a_notice():
    with freeze_time("2026-02-20 12:00:00"):
        world = World()
    with freeze_time("2026-03-10 12:00:00"):
        po = deliver(world, 40)
        flour = InputRequest.objects.get(production_order=po, item__name="Flour")
        flour.quantity, flour.status, flour.received_at = D(36), "received", services.timezone.now()
        flour.save()  # 24 kg were needed for 40 loaves
    with freeze_time("2026-04-02 12:00:00"):
        measure.run_plausibility(date(2026, 3, 1))
    notice = AuditEvent.objects.get(verb="plausibility.inputs_high")
    assert notice.data["value"] == "1.5000"


def test_closing_is_blocked_while_orders_are_open(world):
    line = services.place_order(world.buyer(), world.bread, D(2))
    blockers = us.close_unit(world.bakery_unit, "Stopping", member=world.baker)
    world.bakery_unit.refresh_from_db()
    assert world.bakery_unit.status == "closing" and any("production orders" in b for b in blockers)
    services.cancel_line(line, line.order.buyer)
    assert us.close_unit(world.bakery_unit, "Stopping", member=world.baker) == []
    world.bakery_unit.refresh_from_db()
    assert world.bakery_unit.status == "closed"


def test_closing_is_blocked_while_future_sessions_have_bookings(salon):
    customer = salon.customer()
    slot = salon.slot()
    services.book(customer, slot)
    blockers = us.close_unit(salon.unit, "Stopping", member=salon.provider)
    assert any("coming sessions" in b for b in blockers)
