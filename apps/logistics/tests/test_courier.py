from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.ledger import services as ledger
from apps.logistics import quotes, services
from apps.logistics.models import Shipment
from apps.market import services as market
from apps.units.models import HoursEntry

from .conftest import make_courier, member_at, ready_line

pytestmark = pytest.mark.django_db
D = Decimal
DELIVER = {"mode": "deliver", "postcode": "10405", "country": "DE"}


def test_a_three_kilometre_delivery_costs_the_hours_plus_depreciation(world):
    courier, unit, offer, co = make_courier(world)
    a = SimpleNamespace(lat=D("52.000000"), lng=D("13.000000"))
    b = SimpleNamespace(lat=D("52.026979"), lng=D("13.000000"))  # 3.000 km due north
    uniq, eur = quotes.courier_quote(co, a, b)
    # 3 km at 15 km/h is 12 minutes, plus 5 stop minutes: 17/60 = 0.2833 UNIQ; the bicycle: 10 / 1000 = 0.01 per use
    assert uniq == D("0.2933") and eur == D("0.00")
    assert quotes.courier_minutes(co, 3).quantize(D("0.01")) == D("17.00")


def test_the_delivery_is_its_own_line_held_and_paid_like_a_service(world):
    courier, unit, offer, co = make_courier(world)
    buyer = member_at("b@x.org", "10405")
    before = ledger.available(ledger.member_account(buyer))
    line = ready_line(world, buyer, 2, delivery=DELIVER)
    shipment = Shipment.objects.get(line=line)
    assert shipment.mode == "unicorn_courier" and shipment.courier_line.offer == offer
    cl = shipment.courier_line
    assert cl.total_uniq == shipment.uniq_cost > 0 and cl.hold.status == "active"
    assert ledger.available(ledger.member_account(buyer)) == before - line.total_uniq - cl.total_uniq

    services.confirm_mode(shipment, world.baker)
    services.mark_sent(shipment, world.baker)
    services.courier_delivered(shipment, courier)
    shipment.refresh_from_db()
    assert shipment.status == "delivered" and shipment.courier_minutes >= 5
    market.confirm_received(line, buyer)
    line.refresh_from_db()
    cl.refresh_from_db()
    assert line.status == "delivered" and cl.status == "delivered"
    entry = HoursEntry.objects.get(ref_type="orderline", ref_id=str(cl.pk))
    assert entry.member == courier and entry.minutes == shipment.courier_minutes and entry.status == "paid"


def test_the_make_or_buy_rule_picks_the_courier_when_it_is_cheaper_in_hours(world):
    make_courier(world)
    services_carrier = pytest.importorskip("apps.logistics.services")
    from .conftest import make_carrier

    make_carrier(base="40")  # 40 euros at the planning rate is more hours than the courier's 0.29
    p = services_carrier.propose(world.bakery_unit, "DE", "10405")
    assert p.mode == "unicorn_courier" and p.uniq > 0


def test_only_a_courier_worker_marks_it_delivered(world):
    courier, unit, offer, co = make_courier(world)
    buyer = member_at("b@x.org", "10405")
    line = ready_line(world, buyer, 1, delivery=DELIVER)
    shipment = Shipment.objects.get(line=line)
    services.confirm_mode(shipment, world.baker)
    with pytest.raises(services.LogisticsError, match="selling unit"):
        services.mark_sent(shipment, world.miller)
    services.mark_sent(shipment, world.baker)
    with pytest.raises(services.LogisticsError, match="courier unit"):
        services.courier_delivered(shipment, world.miller)
