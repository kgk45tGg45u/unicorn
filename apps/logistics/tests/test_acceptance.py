"""Phase 12 acceptance: deliverable offers, a courier delivery paid like a service, and a carrier far away."""

from decimal import Decimal

import pytest

from apps.catalogue import services as cat
from apps.logistics import geo, quotes, services
from apps.logistics.models import Shipment
from apps.market import services as market
from apps.market.tests.conftest import unit_for
from apps.outside import services as outside
from apps.tradefund import services as fund
from apps.tradefund.models import PurchaseRequest
from apps.units.models import HoursEntry

from .conftest import IBAN, make_carrier, make_courier, member_at, ready_line

pytestmark = pytest.mark.django_db
D = Decimal


def test_a_member_three_kilometres_from_the_bakery_sees_deliverable(world, client):
    member = member_at("near@x.org", "10405")
    assert 2 < geo.distance_km(world.bakery_unit, "DE", "10405") < 4
    client.force_login(member.user)
    assert "Deliverable to you" in client.get("/market/?q=Bread").content.decode()


def test_a_courier_delivery_is_quoted_held_delivered_confirmed_and_paid(world):
    courier, unit, offer, co = make_courier(world)
    buyer = member_at("near@x.org", "10405")
    km = geo.distance_km(world.bakery_unit, "DE", "10405")
    expected = (quotes.courier_minutes(co, km) / 60 + D("0.01")).quantize(D("0.0001"))
    line = ready_line(world, buyer, 2, delivery={"mode": "deliver", "postcode": "10405", "country": "DE"})
    shipment = Shipment.objects.get(line=line)
    assert shipment.mode == "unicorn_courier" and shipment.uniq_cost == expected
    assert shipment.courier_line.hold.status == "active"
    services.confirm_mode(shipment, world.baker)
    services.mark_sent(shipment, world.baker)
    services.courier_delivered(shipment, courier)
    market.confirm_received(line, buyer)
    shipment.courier_line.refresh_from_db()
    assert shipment.courier_line.status == "delivered"
    assert HoursEntry.objects.get(ref_id=str(shipment.courier_line.pk)).status == "paid"


def test_a_member_far_away_gets_a_carrier_proposal_and_the_fund_gets_a_purchase_request(world):
    make_courier(world)
    make_carrier()
    buyer = member_at("far@x.org", "20095")
    assert not geo.covers(world.bakery_unit, "DE", "20095")
    line = market.place_order(
        buyer, world.bread, D(1), delivery={"mode": "deliver", "postcode": "20095", "country": "DE"}
    )
    shipment = Shipment.objects.get(line=line)
    assert shipment.mode == "capitalist_carrier" and shipment.uniq_cost == 0
    assert PurchaseRequest.objects.filter(source="operations", est_price=D("5.49")).count() == 1


def test_the_order_form_chooses_delivery(world, client):
    make_carrier()
    buyer = member_at("far@x.org", "20095")
    client.force_login(buyer.user)
    response = client.post(
        f"/offers/{world.bread.pk}/order/",
        {"quantity": "1", "delivery": "deliver", "postcode": "20095", "country": "DE"},
    )
    assert response.status_code == 302
    assert Shipment.objects.get().mode == "capitalist_carrier"
    page = client.get(f"/offers/{world.bread.pk}/").content.decode()
    assert "Deliver to me" in page


def test_an_outside_customer_gets_a_carrier_and_confirms_by_the_link(world, client):
    make_carrier()
    fund.become_holder(world.baker, "EUR", IBAN)
    outside.activate_seller(world.baker, "Baker Bakery", "Mill Road 1")
    outside.apply_outside_offer(world.bread, "5.00", "EUR", world.baker)
    order = outside.place_outside_order(
        world.bread, 1, "Cora", "c@example.org", "Street 5", "DE", True, True,
        delivery={"mode": "deliver", "postcode": "20095", "country": "DE"},
    )  # fmt: skip
    shipment = Shipment.objects.get(order=order)
    assert shipment.mode == "capitalist_carrier"
    outside.confirm_customer_payment(order, world.baker, "5.00")
    line = order.lines.get()
    po = line.production_order
    market.start_production(po, world.baker)
    market.complete_production(po, world.baker, 1)
    services.confirm_mode(shipment, world.baker)
    services.mark_sent(shipment, world.baker, "TRACK1")
    page = client.get(f"/shop/order/{order.public_token}/")
    assert b"It arrived" in page.content
    client.post(f"/shop/order/{order.public_token}/received/")
    shipment.refresh_from_db()
    line.refresh_from_db()
    assert shipment.status == "delivered" and line.status == "delivered"
    assert cat and unit_for
