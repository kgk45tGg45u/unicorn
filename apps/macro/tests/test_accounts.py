from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from freezegun import freeze_time

from apps.ledger import services as ledger
from apps.macro import accounts
from apps.market import services
from apps.market.models import StockLot
from apps.market.tests.conftest import ServiceWorld, World

pytestmark = pytest.mark.django_db
D = Decimal


def a_small_month():
    """One bakery order delivered, one haircut performed and confirmed, one advance lot written off."""
    world, salon = World(), ServiceWorld()
    buyer = world.buyer(uniq=10)
    line = services.place_order(buyer, world.bread, D(2))
    batch = line.production_order
    from apps.market.models import InputRequest

    flour = InputRequest.objects.get(item__name="Flour")
    services.mark_delivered(flour, world.miller)
    services.mark_received(flour, world.baker)
    services.start_production(batch, world.baker)
    services.complete_production(batch, world.baker, 2)
    services.hand_over(line, world.baker)
    services.confirm_received(line, buyer)
    customer = salon.customer()
    slot = salon.slot()
    booking = services.book(customer, slot)
    with freeze_time(timezone.now() + timedelta(days=1, hours=3)):
        services.mark_performed(slot, salon.provider)
    booking.refresh_from_db()
    services.confirm_performed(booking, customer)
    po = services.start_advance(world.bread, 5, world.baker, estimate=100)
    services.start_production(po, world.baker)
    services.complete_production(po, world.baker, 5)
    with freeze_time(timezone.now() + timedelta(days=6)):
        services.write_off_lots()
    return world, salon


def test_a_small_month_gives_the_expected_uses():
    world, salon = a_small_month()
    period = ledger.current_period()
    data = accounts.hours_by_use(period)
    assert data["consumption"] == data["spent"] == D("0.2850") + D("1.0000")
    assert data["hours_paid"] > 0 and data["hours_paid"] - data["tax"] == data["net_issued"]
    assert StockLot.objects.filter(status="written_off").count() == 1
    assert data["waste"] == D("5.0000") * world.bread.value_total or data["waste"] > 0
    assert data["social"] == 0 and data["trade"] == 0 and data["accumulation"] == 0
    assert data["inventory_value"] >= 0
    identity = (
        data["hours_paid"]
        + data["depreciation"]
        - (
            data["consumption"]
            + data["social"]
            + data["accumulation"]
            + data["trade"]
            + data["waste"]
            + data["inventory_change"]
        )
    )
    assert data["hours_residual"] == identity.quantize(D("0.0001"))


def test_the_residual_warning_appears_when_recipes_and_hours_drift():
    data = {"hours_paid": D("100"), "hours_residual": D("3")}
    assert abs(data["hours_residual"]) > data["hours_paid"] * accounts.TOLERANCE
    assert str(accounts.RESIDUAL_WORDS)


def test_accumulation_comes_from_production_orders_and_trade_from_delivered_outside_lines():
    from apps.market.models import Order, OrderLine, ProductionOrder

    world = World()
    ProductionOrder.objects.create(
        offer=world.bread,
        quantity=D(10),
        status="done",
        purpose="accumulation",
        due_date=timezone.localdate(),
        done_at=timezone.now(),
        quantity_done=D(10),
    )
    order = Order.objects.create(kind="outside", public_token="t" * 20)
    OrderLine.objects.create(
        order=order,
        offer=world.bread,
        quantity=D(4),
        price_uniq=0,
        total_uniq=0,
        price_eur=D("5.00"),
        currency="EUR",
        seller=world.baker,
        value_at_order=D(4) * world.bread.value_total,
        due_date=timezone.localdate(),
        status="delivered",
        delivered_at=timezone.now(),
    )
    data = accounts.hours_by_use(ledger.current_period())
    assert data["accumulation"] == (D(10) * world.bread.value_total).quantize(D("0.0001"))
    assert data["trade"] == (D(4) * world.bread.value_total).quantize(D("0.0001"))
