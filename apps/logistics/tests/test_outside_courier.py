"""Outside customers pay a courier in euros; no UNIQ move for the payment (HF-4), and the fund keeps the money."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.ledger.models import Entry
from apps.ledger.services import current_period
from apps.logistics import geo, services
from apps.logistics.models import Shipment
from apps.macro import accounts
from apps.market import services as market
from apps.outside import services as outside
from apps.tradefund import books
from apps.tradefund import services as fund
from apps.tradefund.models import Holder
from apps.units.models import HoursEntry

from .conftest import IBAN, make_carrier, make_courier

pytestmark = pytest.mark.django_db
D = Decimal
HERE = {"mode": "deliver", "postcode": "10405", "country": "DE"}


def _outside_shop(world):
    fund.become_holder(world.baker, "EUR", IBAN)
    outside.activate_seller(world.baker, "Baker Bakery", "Mill Road 1")
    outside.apply_outside_offer(world.bread, "5.00", "EUR", world.baker)


def _courier_sells(courier, co, base="4.00", per_km="1.00"):
    fund.become_holder(courier, "EUR", IBAN)
    outside.activate_seller(courier, "Fast Couriers", "Bike Lane 2")
    return outside.set_courier_rates(courier, co, base, per_km, courier)


def _order(world, delivery=HERE):
    return outside.place_outside_order(
        world.bread, 2, "Cora", "c@example.org", "Street 5", "DE", True, True, delivery=delivery
    )


def test_an_outside_customer_is_offered_a_courier_in_euros(world):
    _outside_shop(world)
    courier, unit, offer, co = make_courier(world)
    _courier_sells(courier, co)
    order = _order(world)
    shipment = Shipment.objects.get(order=order)
    km = geo.distance_km(world.bakery_unit, "DE", "10405")
    assert shipment.mode == "unicorn_courier" and shipment.uniq_cost == 0
    assert shipment.eur_cost == (D("4.00") + D(str(km)) * D("1.00")).quantize(D("0.01"))
    leg = shipment.courier_line
    assert leg.order.kind == "outside" and leg.order != order and leg.seller == courier
    assert leg.price_uniq == 0 and leg.hold is None and leg.price_eur == shipment.eur_cost


def test_without_euro_rates_a_courier_is_not_offered_to_outsiders(world):
    _outside_shop(world)
    make_courier(world)
    make_carrier()
    assert Shipment.objects.get(order=_order(world)).mode == "capitalist_carrier"


def test_the_cheaper_in_euros_wins_for_an_outsider(world):
    _outside_shop(world)
    courier, unit, offer, co = make_courier(world)
    _courier_sells(courier, co, base="40.00", per_km="0")
    make_carrier(base="5.49")
    assert Shipment.objects.get(order=_order(world)).mode == "capitalist_carrier"


def test_hf04_the_customers_euros_move_no_uniq_and_the_fund_keeps_them(world):
    _outside_shop(world)
    courier, unit, offer, co = make_courier(world)
    _courier_sells(courier, co)
    order = _order(world)
    shipment = Shipment.objects.get(order=order)
    leg_order = shipment.courier_line.order
    entries = Entry.objects.count()
    invoice = outside.confirm_customer_payment(leg_order, courier, shipment.eur_cost)
    assert Entry.objects.count() == entries  # HF-4: nothing in UNIQ
    assert invoice.seller == courier and "§ 19" in invoice.vat_note
    holder = Holder.objects.get(member=courier)
    assert books.holding(holder) == invoice.setaside > 0  # the trade fund keeps it to buy things later
    shipment.courier_line.refresh_from_db()
    assert shipment.courier_line.status == "ready"


def test_the_whole_delivery_the_courier_is_paid_hours_and_trade_rises(world):
    _outside_shop(world)
    courier, unit, offer, co = make_courier(world)
    _courier_sells(courier, co)
    order = _order(world)
    shipment = Shipment.objects.get(order=order)
    leg = shipment.courier_line
    services.confirm_mode(shipment, world.baker)
    outside.confirm_customer_payment(order, world.baker, outside.total_of(order.lines.get()))
    po = order.lines.get().production_order
    market.start_production(po, world.baker)
    market.complete_production(po, world.baker, 2)
    with pytest.raises(services.LogisticsError, match="not paid the courier"):
        services.mark_sent(shipment, world.baker)
    outside.confirm_customer_payment(leg.order, courier, leg.price_eur)
    services.mark_sent(shipment, world.baker)
    services.courier_delivered(shipment, courier)
    shipment.refresh_from_db()
    assert shipment.status == "delivered"
    with pytest.raises(outside.OutsideError, match="not on its way|no parcel"):
        outside.customer_received(leg.order)  # only the product order has the shipment
    outside.customer_received(order)
    leg.refresh_from_db()
    assert leg.status == "delivered" and order.lines.get().status == "delivered"
    hours = HoursEntry.objects.get(ref_type="orderline", ref_id=str(leg.pk))
    assert hours.member == courier and hours.status == "paid" and hours.minutes == shipment.courier_minutes
    trade = accounts.hours_by_use(current_period())["trade"]
    assert trade >= leg.value_at_order > 0  # the trip's hours count as trade, like the product's


def test_an_undelivered_confirmation_counts_after_the_delay(world):
    _outside_shop(world)
    courier, unit, offer, co = make_courier(world)
    _courier_sells(courier, co)
    order = _order(world)
    shipment = Shipment.objects.get(order=order)
    leg = shipment.courier_line
    services.confirm_mode(shipment, world.baker)
    outside.confirm_customer_payment(order, world.baker, outside.total_of(order.lines.get()))
    outside.confirm_customer_payment(leg.order, courier, leg.price_eur)
    po = order.lines.get().production_order
    market.start_production(po, world.baker)
    market.complete_production(po, world.baker, 2)
    services.mark_sent(shipment, world.baker)
    services.courier_delivered(shipment, courier)
    assert outside.auto_confirm_deliveries(timezone.now()) == 0
    assert outside.auto_confirm_deliveries(timezone.now() + timedelta(days=7)) == 1
    assert order.lines.get().status == "delivered"
    assert outside.auto_confirm_deliveries(timezone.now() + timedelta(days=8)) == 0


def test_only_the_council_sets_courier_rates_and_the_seller_must_be_a_worker(world):
    from apps.units.tests.conftest import make_member

    courier, unit, offer, co = make_courier(world)
    fund.become_holder(courier, "EUR", IBAN)
    outside.activate_seller(courier, "Fast Couriers", "Bike Lane 2")
    stranger = make_member("s@x.org", "S")
    with pytest.raises(outside.OutsideError, match="council"):
        outside.set_courier_rates(stranger, co, "4", "1", courier)
    with pytest.raises(outside.OutsideError, match="worker"):
        outside.set_courier_rates(courier, co, "4", "1", stranger)
    with pytest.raises(outside.OutsideError, match="above zero"):
        outside.set_courier_rates(courier, co, "0", "0", courier)
