from decimal import Decimal

import pytest

from apps.ledger import services as ledger
from apps.logistics import services
from apps.logistics.models import Shipment
from apps.market import services as market
from apps.tradefund.models import PurchaseRequest

from .conftest import make_carrier, make_courier, member_at, ready_line

pytestmark = pytest.mark.django_db
D = Decimal
FAR = {"mode": "deliver", "postcode": "20095", "country": "DE"}


def test_with_no_courier_covering_a_carrier_is_proposed_and_shipping_costs_no_uniq(world):
    make_courier(world)  # covers Berlin only
    make_carrier()
    buyer = member_at("far@x.org", "20095")
    before = ledger.available(ledger.member_account(buyer))
    line = market.place_order(buyer, world.bread, D(2), delivery=FAR)
    shipment = Shipment.objects.get(line=line)
    assert shipment.mode == "capitalist_carrier" and shipment.courier_line is None
    assert shipment.uniq_cost == 0 and shipment.eur_cost == D("5.49")
    assert ledger.available(ledger.member_account(buyer)) == before - line.total_uniq  # nothing extra in UNIQ


def test_the_carriers_purchase_request_is_created_from_the_trade_fund(world):
    make_carrier()
    buyer = member_at("far@x.org", "20095")
    line = market.place_order(buyer, world.bread, D(1), delivery=FAR)
    shipment = Shipment.objects.get(line=line)
    request = shipment.purchase_request
    assert isinstance(request, PurchaseRequest) and request.source == "operations"
    assert request.est_price == D("5.49") and request.unit == world.bakery_unit


def test_the_carrier_flow_needs_tracking_and_the_buyers_confirmation(world):
    make_carrier()
    buyer = member_at("far@x.org", "20095")
    line = ready_line(world, buyer, 1, delivery=FAR)
    shipment = Shipment.objects.get(line=line)
    with pytest.raises(services.LogisticsError, match="confirm how"):
        services.mark_sent(shipment, world.baker, "JJD123")
    services.confirm_mode(shipment, world.baker)
    with pytest.raises(services.LogisticsError, match="tracking"):
        services.mark_sent(shipment, world.baker, " ")
    services.mark_sent(shipment, world.baker, "JJD123")
    services.carrier_delivered(shipment, buyer)
    shipment.refresh_from_db()
    line.refresh_from_db()
    assert shipment.status == "delivered" and shipment.tracking == "JJD123" and line.status == "delivered"


def test_no_courier_and_no_carrier_means_pickup_only(world):
    buyer = member_at("far@x.org", "20095")
    with pytest.raises(market.MarketError, match="pick it up"):
        market.place_order(buyer, world.bread, D(1), delivery=FAR)


def test_the_responsible_may_change_a_proposal_and_the_side_effects_follow(world):
    courier, unit, offer, co = make_courier(world)
    make_carrier(base="1.00")  # a very cheap carrier is proposed first
    buyer = member_at("b@x.org", "10405")
    line = market.place_order(
        buyer, world.bread, D(1), delivery={"mode": "deliver", "postcode": "10405", "country": "DE"}
    )
    shipment = Shipment.objects.get(line=line)
    assert shipment.mode == "capitalist_carrier"
    services.confirm_mode(shipment, world.baker, "unicorn_courier")
    shipment.refresh_from_db()
    assert shipment.mode == "unicorn_courier" and shipment.courier_line.hold.status == "active"
    assert shipment.confirmed_by_responsible and shipment.carrier is None
    services.confirm_mode(shipment, world.baker, "capitalist_carrier")
    shipment.refresh_from_db()
    assert shipment.courier_line is None and shipment.carrier is not None


def test_hf03_carrier_euros_never_enter_an_offers_uniq_price(world):
    from apps.catalogue import services as cat

    make_carrier()
    buyer = member_at("far@x.org", "20095")
    before = (world.bread.value_total, world.bread.euro_content)
    line = market.place_order(buyer, world.bread, D(1), delivery=FAR)
    cat.recompute_values()
    world.bread.refresh_from_db()
    assert (world.bread.value_total, world.bread.euro_content) == before  # the shipping euros are in no price
    assert line.price_uniq == world.bread.value_total
