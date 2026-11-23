import pytest

from apps.ledger.models import Account, Entry
from apps.logistics import services
from apps.logistics.models import Shipment
from apps.market import services as market
from apps.units.tests.conftest import make_member

from .conftest import member_at, ready_line

pytestmark = pytest.mark.django_db


def test_only_points_inside_the_cover_area_are_offered(world):
    baker = world.baker
    near = services.create_point(baker, "Corner shop", "Main Street 1", "10405", unit=None)
    far = services.create_point(baker, "Hamburg shop", "Harbour 2", "20095")
    services.serve_point(world.bakery_unit, near, baker)
    with pytest.raises(services.LogisticsError, match="outside the unit's cover area"):
        services.serve_point(world.bakery_unit, far, baker)
    assert services.points_for(world.bakery_unit) == [near]
    with pytest.raises(services.LogisticsError, match="worker"):
        services.serve_point(world.bakery_unit, near, make_member("x@x.org", "X"))


def test_an_order_can_only_go_to_a_point_the_unit_serves(world):
    near = services.create_point(world.baker, "Corner shop", "Main Street 1", "10405")
    buyer = member_at("b@x.org", "10405")
    with pytest.raises(market.MarketError, match="not served"):
        market.place_order(buyer, world.bread, 1, delivery={"mode": "pickup", "point": near})


def test_the_hand_over_steps_unit_then_manager_then_buyer(world):
    manager = make_member("m@x.org", "Manager")
    point = services.create_point(world.baker, "Corner shop", "Main Street 1", "10405", manager=manager)
    services.serve_point(world.bakery_unit, point, world.baker)
    buyer = member_at("b@x.org", "10405")
    line = ready_line(world, buyer, 2, delivery={"mode": "pickup", "point": point})
    shipment = Shipment.objects.get(line=line)
    assert shipment.mode == "pickup_point" and shipment.status == "planned"
    with pytest.raises(services.LogisticsError, match="not brought"):
        services.point_confirm(shipment, manager)
    services.hand_to_point(shipment, world.baker)
    with pytest.raises(services.LogisticsError, match="manager"):
        services.point_confirm(shipment, world.baker)
    services.point_confirm(shipment, manager)
    line.refresh_from_db()
    assert line.status == "handed_over"
    market.confirm_received(line, buyer)
    line.refresh_from_db()
    shipment.refresh_from_db()
    assert line.status == "delivered" and shipment.status == "delivered"
    assert Entry.objects.filter(account__kind=Account.FUND1, amount__gt=0).exists()
