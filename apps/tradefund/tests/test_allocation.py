from decimal import Decimal

import pytest

from apps.catalogue import services as cat
from apps.catalogue.models import Offer
from apps.market.tests.conftest import World
from apps.tradefund import allocation, books
from apps.tradefund.models import PurchaseRequest
from apps.units import services as us
from apps.units.tests.conftest import make_member, make_unit

from .conftest import make_holder, set_param

pytestmark = pytest.mark.django_db
D = Decimal


def dairy(world):
    """A second unit with a much more euro-hungry offer: 5 euros of milk per cheese."""
    member = make_member("dairy@x.org", "Dairy")
    unit = make_unit("dairy")
    us.add_first_worker(unit, member)
    item = cat.create_item("Cheese", "product", "pc")
    offer = cat.create_offer(
        member, unit, item, batch_size=D(10), cycle_days=1, setup_minutes=0, direct_minutes_per_batch=600
    )
    cat.add_input(member, offer, "Milk", "l", D(100), "buy_outside", euro_price_estimate=D("0.5"))
    cat.publish_offer(offer, member)
    cat.recompute_values()
    offer.refresh_from_db()
    return member, unit, offer


def waiting(unit, requester, est="50.00", source="recipe_input", what="Materials"):
    return PurchaseRequest.objects.create(
        requester=requester, unit=unit, description=what, est_price=D(est), source=source, status="waiting_for_euros"
    )


def test_with_too_few_euros_the_most_euro_hungry_offer_pauses_first_and_44_percent_stay():
    w = World()
    _m, dairy_unit, cheese = dairy(w)
    waiting(w.bakery_unit, w.baker)
    waiting(dairy_unit, _m)
    result = allocation.allocate()
    cheese.refresh_from_db()
    w.bread.refresh_from_db()
    assert cheese.status == "paused" and cheese.paused_for_euros
    assert "short of euros" in cheese.status_note
    assert w.bread.status == "active" and not w.bread.paused_for_euros  # the next one would pass the 56% limit
    active = Offer.objects.filter(status="active").count()
    assert active / (active + 1) >= D("0.44")
    assert result["paused"] == 1
    from apps.tickets.models import Notification

    assert Notification.objects.filter(member=_m, text__contains="short of euros").exists()


def test_a_paused_offer_cannot_be_ordered():
    from apps.market import services as market
    from apps.market.tests.conftest import fund

    w = World()
    _m, dairy_unit, cheese = dairy(w)
    waiting(dairy_unit, _m)
    allocation.allocate()
    buyer = make_member("b@x.org", "B")
    fund(buyer, 10)
    with pytest.raises(market.MarketError, match="not available"):
        market.place_order(buyer, cheese, 1)


def test_offers_open_again_when_euros_allow():
    w = World()
    m, dairy_unit, cheese = dairy(w)
    req = waiting(dairy_unit, m)
    allocation.allocate()
    cheese.refresh_from_db()
    assert cheese.paused_for_euros
    make_holder("h@x.org", "H", amount=400)
    result = allocation.allocate()
    cheese.refresh_from_db()
    req.refresh_from_db()
    assert result["unpaused"] == 1 and cheese.status == "active" and not cheese.paused_for_euros
    assert req.status != "waiting_for_euros"


def test_with_euro_priority_goods_the_order_of_tools_and_materials_swaps():
    w = World()
    tool = waiting(w.bakery_unit, w.baker, "50.00", source="tool", what="An oven")
    material = waiting(w.mill_unit, w.miller, "50.00", source="recipe_input", what="Grain")
    make_holder("h@x.org", "H", amount=60)
    allocation.allocate()
    tool.refresh_from_db()
    material.refresh_from_db()
    assert tool.status != "waiting_for_euros" and material.status == "waiting_for_euros"  # tools first (default)


def test_euro_priority_goods_funds_materials_first():
    w = World()
    tool = waiting(w.bakery_unit, w.baker, "50.00", source="tool", what="An oven")
    material = waiting(w.mill_unit, w.miller, "50.00", source="recipe_input", what="Grain")
    set_param("economy.euro_priority", "goods")
    make_holder("h@x.org", "H", amount=60)
    allocation.allocate()
    tool.refresh_from_db()
    material.refresh_from_db()
    assert material.status != "waiting_for_euros" and tool.status == "waiting_for_euros"


def test_reserve_months_are_computed_right():
    assert allocation.reserve_months() is None  # nothing paid out yet
    h = make_holder("h@x.org", "H", amount=1000)
    books.post_fund(h, "payment_out", -100, "materials", "group_purchase")
    assert allocation.monthly_outgoings_eur() == D("100.00")
    assert allocation.free_holdings_eur() == D("900.00")
    assert allocation.reserve_months() == D("9.00")
    books.post_fund(h, "reserve_mark", 100, "reserve", "internal")
    assert allocation.reserve_months() == D("8.00")  # the reserve is not free


def test_the_marketplace_shows_paused_offers(client):
    w = World()
    m, dairy_unit, cheese = dairy(w)
    waiting(dairy_unit, m)
    allocation.allocate()
    client.force_login(w.baker.user)
    response = client.get("/market/")
    assert response.status_code == 200
    assert b"Paused: the trade fund is short of euros" in response.content
