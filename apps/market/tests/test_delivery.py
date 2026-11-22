from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.utils import timezone
from freezegun import freeze_time

from apps.core.jobs import run_due
from apps.core.models import AuditEvent, Job
from apps.ledger import services as ledger
from apps.market import services
from apps.market.models import OrderLine, StockLot

pytestmark = pytest.mark.django_db
D = Decimal


def ready_line(world, quantity=2, buyer=None, batch=None):
    buyer = buyer or world.buyer()
    line = services.place_order(buyer, world.bread, D(quantity))
    po = line.production_order
    services.start_production(po, world.baker)
    services.complete_production(po, world.baker, batch or quantity)
    line.refresh_from_db()
    return buyer, line


def test_confirming_captures_the_hold_into_fund_1(world):
    buyer, line = ready_line(world)
    services.hand_over(line, world.baker)
    fund1 = ledger.balance(ledger.fund1())
    services.confirm_received(line, buyer)
    line.refresh_from_db()
    assert line.status == "delivered" and line.delivered_at and line.hold.status == "captured"
    assert ledger.balance(ledger.fund1()) - fund1 == D("0.2850")
    tx = ledger.Transaction.objects.filter(kind="purchase").latest("seq")
    assert tx.reason == "Bought 2 Bread from Bakery"
    assert ledger.balance(ledger.member_account(buyer)) == D(10) - D("0.2850")


def test_a_line_served_from_the_shelf_draws_its_stock_when_confirmed(world):
    ready_line(world, batch=40)  # 38 go to the shelf
    buyer = world.buyer("late@x.org")
    line = services.place_order(buyer, world.bread, D(3))
    services.hand_over(line, world.baker)
    lot = StockLot.objects.get()
    assert lot.quantity_left == 38  # not drawn before the buyer confirms
    services.confirm_received(line, buyer)
    lot.refresh_from_db()
    assert lot.quantity_left == 35 and services.reserved(lot) == 0


def test_only_the_buyer_confirms_and_only_a_worker_hands_over(world):
    buyer, line = ready_line(world)
    with pytest.raises(services.MarketError, match="work in this unit"):
        services.hand_over(line, buyer)
    with pytest.raises(services.MarketError, match="not your order"):
        services.confirm_received(line, world.baker)


def test_an_order_that_is_not_ready_cannot_be_handed_over(world):
    line = services.place_order(world.buyer(), world.bread, D(2))
    with pytest.raises(services.MarketError, match="not ready"):
        services.hand_over(line, world.baker)


def test_handing_over_asks_the_buyer_to_confirm(world):
    buyer, line = ready_line(world)
    mail.outbox.clear()
    services.hand_over(line, world.baker)
    assert any("confirm you received" in m.subject for m in mail.outbox)


def test_auto_confirm_after_48_hours(world):
    buyer, line = ready_line(world)
    services.hand_over(line, world.baker)
    with freeze_time(timezone.now() + timedelta(hours=47)):
        assert services.auto_confirm_deliveries() == 0
    with freeze_time(timezone.now() + timedelta(hours=49)):
        assert services.auto_confirm_deliveries() == 1
        assert services.auto_confirm_deliveries() == 0  # safe to run twice
    line.refresh_from_db()
    assert line.status == "delivered" and line.hold.status == "captured"
    assert AuditEvent.objects.filter(verb="order.delivered", actor_ref="system").exists()


def test_the_job_queued_at_hand_over_confirms_when_its_time_comes(world):
    buyer, line = ready_line(world)
    services.hand_over(line, world.baker)
    run_due()  # the price run queued by the offers
    job = Job.objects.get(kind="market.auto_confirm_line")
    assert job.status == "queued" and job.run_after > timezone.now() + timedelta(hours=47)
    with freeze_time(timezone.now() + timedelta(hours=49)):
        run_due()
    job.refresh_from_db()
    line.refresh_from_db()
    assert job.status == "done" and line.status == "delivered"


def test_a_dispute_keeps_the_hold_and_stops_the_auto_confirm(world):
    buyer, line = ready_line(world)
    services.hand_over(line, world.baker)
    services.dispute(line, buyer, "damaged", "The bag was torn")
    with freeze_time(timezone.now() + timedelta(hours=60)):
        assert services.auto_confirm_deliveries() == 0
    line.refresh_from_db()
    assert line.status == "handed_over" and line.hold.status == "active"
    assert "damaged" in line.dispute_text
    assert AuditEvent.objects.filter(verb="order.disputed").exists()
    with pytest.raises(services.MarketError, match="what went wrong"):
        services.dispute(line, buyer, "other")


def test_refusing_after_the_start_still_charges_the_buyer(world):
    buyer, line = ready_line(world)
    mail.outbox.clear()
    fund1 = ledger.balance(ledger.fund1())
    services.refuse(line, buyer)
    line.refresh_from_db()
    assert line.status == "refused" and line.hold.status == "captured"
    assert ledger.balance(ledger.fund1()) - fund1 == D("0.2850")
    lot = StockLot.objects.get()
    assert lot.origin == "refused" and lot.quantity == 2 and lot.production_order == line.production_order
    assert any("binding" in m.body for m in mail.outbox)


def test_refusing_something_not_yet_made_is_a_free_cancel(world):
    buyer = world.buyer()
    line = services.place_order(buyer, world.bread, D(2))
    services.refuse(line, buyer)
    line.refresh_from_db()
    assert line.status == "cancelled" and line.hold.status == "released"
    assert not StockLot.objects.exists()


def test_a_line_from_the_shelf_can_be_refused_for_free(world):
    ready_line(world, batch=40)
    buyer = world.buyer("late@x.org")
    line = services.place_order(buyer, world.bread, D(3))
    assert line.status == OrderLine.FROM_STOCK
    services.refuse(line, buyer)
    line.refresh_from_db()
    assert line.status == "cancelled" and line.hold.status == "released"
