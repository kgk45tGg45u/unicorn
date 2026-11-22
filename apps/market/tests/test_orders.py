from decimal import Decimal

import pytest

from apps.catalogue import services as cat
from apps.ledger import services as ledger
from apps.market import services
from apps.market.models import OrderLine
from apps.market.tests.conftest import fund
from apps.members.models import Member
from apps.units.tests.conftest import make_member

pytestmark = pytest.mark.django_db
D = Decimal


def test_an_order_holds_the_price_and_keeps_the_line(world):
    buyer = world.buyer()
    line = services.place_order(buyer, world.bread, D(2))
    assert line.price_uniq == D("0.1425") and line.total_uniq == D("0.2850")
    assert line.hold.amount == D("0.2850") and line.hold.status == "active"
    assert ledger.available(ledger.member_account(buyer)) == D(10) - D("0.2850")
    assert line.due_date is not None


def test_hf03_price_fixed_at_ordering(world):
    buyer = world.buyer()
    line = services.place_order(buyer, world.bread, D(2))
    # the unit makes the bread with fewer working hours: the price of new orders falls
    cat.update_offer(world.baker, world.bread, direct_minutes_per_batch=120)
    cat.recompute_values()
    world.bread.refresh_from_db()
    assert world.bread.value_total < D("0.1425")
    line.refresh_from_db()
    assert line.price_uniq == D("0.1425") and line.total_uniq == D("0.2850")
    assert line.hold.amount == D("0.2850")
    newer = services.place_order(buyer, world.bread, D(2))
    assert newer.price_uniq == world.bread.value_total


def test_hf08_former_member_can_order(world):
    buyer = world.buyer()
    buyer.status = Member.FORMER
    buyer.save()
    assert services.place_order(buyer, world.bread, D(1)).status != "cancelled"


def test_an_applicant_cannot_order(world):
    applicant = make_member("app@x.org", "App", verified=False)
    with pytest.raises(services.MarketError, match="Only members can order"):
        services.place_order(applicant, world.bread, D(1))


def test_not_enough_uniq_is_refused_in_plain_words(world):
    poor = make_member("poor@x.org", "Poor")
    fund(poor, D("0.1"))
    with pytest.raises(services.MarketError, match="Not enough UNIQ available"):
        services.place_order(poor, world.bread, D(1))
    assert OrderLine.objects.count() == 0  # nothing is left behind


def test_a_service_or_a_paused_offer_cannot_be_ordered(world):
    buyer = world.buyer()
    world.bread.status = "paused"
    world.bread.save()
    with pytest.raises(services.MarketError, match="not available"):
        services.place_order(buyer, world.bread, D(1))


def test_quantity_must_be_above_zero(world):
    buyer = world.buyer()
    for bad in (0, -1, "x", D("0.00001")):
        with pytest.raises(services.MarketError):
            services.place_order(buyer, world.bread, bad)


def test_cancelling_releases_the_hold(world):
    buyer = world.buyer()
    line = services.place_order(buyer, world.bread, D(2))
    services.cancel_line(line, buyer)
    line.refresh_from_db()
    assert line.status == "cancelled" and line.hold.status == "released"
    assert ledger.available(ledger.member_account(buyer)) == D(10)


def test_only_the_buyer_can_cancel(world):
    buyer, other = world.buyer(), world.buyer("o@x.org")
    line = services.place_order(buyer, world.bread, D(1))
    with pytest.raises(services.MarketError):
        services.cancel_line(line, other)


def test_the_shortage_cap_shares_a_short_item_out(world, monkeypatch):
    from apps.macro import lights

    monkeypatch.setattr(lights, "item_red", lambda item: True)
    buyer = world.buyer()
    services.place_order(buyer, world.bread, D(2))  # the default cap is 2 a month
    with pytest.raises(services.MarketError, match="short"):
        services.place_order(buyer, world.bread, D(1))
    other = world.buyer("o@x.org")
    assert services.place_order(other, world.bread, D(2))
