from decimal import Decimal

import pytest

from apps.ledger import services as ledger
from apps.ledger.models import Hold
from apps.logistics import services
from apps.logistics.models import Shipment
from apps.market import services as market
from apps.tickets.models import Ticket

from .conftest import make_carrier, make_courier, member_at, ready_line

pytestmark = pytest.mark.django_db
D = Decimal
HERE = {"mode": "deliver", "postcode": "10405", "country": "DE"}


def _sent_by_courier(world):
    courier, unit, offer, co = make_courier(world)
    buyer = member_at("b@x.org", "10405")
    line = ready_line(world, buyer, 2, delivery=HERE)
    shipment = Shipment.objects.get(line=line)
    services.confirm_mode(shipment, world.baker)
    services.mark_sent(shipment, world.baker)
    services.courier_delivered(shipment, courier)
    return courier, buyer, line, shipment


def test_a_damaged_delivery_opens_a_flag_and_the_holds_stay(world):
    courier, buyer, line, shipment = _sent_by_courier(world)
    services.report_problem(shipment, buyer, "damaged", "The loaf is crushed")
    shipment.refresh_from_db()
    line.refresh_from_db()
    assert shipment.status == "failed" and line.disputed_at is not None
    assert Ticket.objects.filter(type="flag", action_payload__dispute__order_line=line.pk).exists()
    assert line.hold.status == "active" and shipment.courier_line.hold.status == "active"
    assert market.auto_confirm_deliveries(now=None) == 0  # a disputed line is never auto-confirmed
    with pytest.raises(services.LogisticsError, match="damaged or missing"):
        services.report_problem(shipment, buyer, "lost", "")


def test_replace_makes_it_again_and_keeps_the_holds(world):
    courier, buyer, line, shipment = _sent_by_courier(world)
    services.report_problem(shipment, buyer, "damaged", "crushed")
    services.resolve(shipment, world.baker, "replace", "We bake it again")
    shipment.refresh_from_db()
    line.refresh_from_db()
    assert shipment.status == "planned" and line.status == "in_production" and line.disputed_at is None
    assert line.hold.status == "active"


def test_a_missing_parcel_is_sent_again(world):
    courier, buyer, line, shipment = _sent_by_courier(world)
    services.report_problem(shipment, buyer, "missing", "Nothing came")
    services.resolve(shipment, world.baker, "replace", "We send it again")
    line.refresh_from_db()
    assert line.status == "ready"


def test_refund_releases_the_holds(world):
    courier, buyer, line, shipment = _sent_by_courier(world)
    before = ledger.available(ledger.member_account(buyer))
    services.report_problem(shipment, buyer, "missing", "Nothing came")
    services.resolve(shipment, world.baker, "refund", "The parcel is lost")
    line.refresh_from_db()
    assert line.status == "cancelled" and line.hold.status == "released"
    assert shipment.courier_line.hold.status == "released" and not Hold.objects.filter(status="active").exists()
    assert ledger.available(ledger.member_account(buyer)) == before + line.total_uniq + shipment.courier_line.total_uniq
    with pytest.raises(services.LogisticsError, match="nothing to settle"):
        services.resolve(shipment, world.baker, "refund", "again")


def test_a_refund_after_payment_posts_a_correction_with_a_reason(world):
    make_carrier()
    buyer = member_at("far@x.org", "20095")
    line = ready_line(world, buyer, 1, delivery={"mode": "deliver", "postcode": "20095", "country": "DE"})
    shipment = Shipment.objects.get(line=line)
    services.confirm_mode(shipment, world.baker)
    services.mark_sent(shipment, world.baker, "T1")
    services.carrier_delivered(shipment, buyer)
    shipment.refresh_from_db()
    shipment.status, shipment.problem = "failed", "damaged: late"
    shipment.save()
    after_paying = ledger.available(ledger.member_account(buyer))
    services.resolve(shipment, world.baker, "refund", "Damaged on arrival")
    line.refresh_from_db()
    assert line.status == "cancelled"
    assert ledger.available(ledger.member_account(buyer)) == after_paying + line.total_uniq


def test_only_the_buyer_reports_and_only_the_unit_resolves(world):
    courier, buyer, line, shipment = _sent_by_courier(world)
    with pytest.raises(services.LogisticsError, match="not your"):
        services.report_problem(shipment, world.baker, "damaged", "x")
    services.report_problem(shipment, buyer, "damaged", "x")
    with pytest.raises(services.LogisticsError, match="selling unit"):
        services.resolve(shipment, courier, "refund", "reason")
    with pytest.raises(services.LogisticsError, match="reason"):
        services.resolve(shipment, world.baker, "refund", " ")
