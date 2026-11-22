from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.utils import timezone
from freezegun import freeze_time

from apps.catalogue.models import Offer
from apps.ledger import services as ledger
from apps.market import services
from apps.market.models import OrderLine, StockLot, WasteRecord
from apps.units.models import HoursEntry

pytestmark = pytest.mark.django_db
D = Decimal


def make_batch(world, quantity, buyer=None):
    """An order that starts a batch, which the baker then completes with `quantity` loaves."""
    line = services.place_order(buyer or world.buyer(), world.bread, D(2))
    po = line.production_order
    services.start_production(po, world.baker)
    services.complete_production(po, world.baker, quantity)
    return line, po


def test_the_extra_output_of_a_batch_goes_to_stock(world):
    line, po = make_batch(world, 40)
    lot = StockLot.objects.get()
    assert lot.quantity == 38 and lot.quantity_left == 38 and lot.origin == "advance"
    assert lot.production_order == po and lot.status == "available"
    assert lot.expires_at is not None and lot.expires_at - lot.made_at == timedelta(days=5)  # bread keeps 5 days


def test_a_new_order_is_served_from_the_shelf(world):
    make_batch(world, 40)
    late = services.place_order(world.buyer("late@x.org"), world.bread, D(3))
    lot = StockLot.objects.get()
    assert late.status == OrderLine.FROM_STOCK and late.stock_lot == lot
    assert late.production_order_id is None and late.due_date == services.today()
    assert services.free_quantity(lot) == 35  # reserved, not yet drawn
    assert lot.quantity_left == 38


def test_the_shelf_is_not_promised_twice(world):
    make_batch(world, 40)
    a, b = world.buyer("a@x.org", uniq=20), world.buyer("b@x.org", uniq=20)
    first = services.place_order(a, world.bread, D(30))
    second = services.place_order(b, world.bread, D(30))  # only 8 left on the shelf: this one is made
    assert first.status == OrderLine.FROM_STOCK
    assert second.status == OrderLine.IN_PRODUCTION


def test_hf09_unsold_advance_becomes_waste(world):
    make_batch(world, 40)
    lot = StockLot.objects.get()
    with freeze_time(timezone.now() + timedelta(days=6)):  # the shelf life of bread is over
        assert services.write_off_lots() == 1
        assert services.write_off_lots() == 0  # safe to run twice
    lot.refresh_from_db()
    waste = WasteRecord.objects.get()
    assert lot.status == "written_off" and lot.quantity_left == 0
    assert waste.quantity == 38 and waste.hours == D(38) * world.bread.value_total  # quantity x value
    assert waste.period == ledger.current_period()


def test_a_lot_with_no_shelf_life_is_written_off_after_the_unsold_days(world):
    world.bread.item.shelf_life_days = None
    world.bread.item.save()
    make_batch(world, 40)
    with freeze_time(timezone.now() + timedelta(days=60)):
        assert services.write_off_lots() == 0
    with freeze_time(timezone.now() + timedelta(days=91)):
        assert services.write_off_lots() == 1


def test_a_waste_record_cannot_be_changed(world):
    make_batch(world, 40)
    with freeze_time(timezone.now() + timedelta(days=6)):
        services.write_off_lots()
    record = WasteRecord.objects.get()
    with pytest.raises(ValueError):
        record.save()
    with pytest.raises(ValueError):
        WasteRecord.objects.update(hours=0)


def test_a_reserved_lot_is_not_written_off(world):
    make_batch(world, 40)
    services.place_order(world.buyer("late@x.org"), world.bread, D(3))
    with freeze_time(timezone.now() + timedelta(days=6)):
        assert services.write_off_lots() == 0


# --- the limit on making ahead ---


def test_the_advance_limit_is_enforced_in_the_first_months_by_the_councils_estimate(world):
    with pytest.raises(services.MarketError, match="more than"):
        services.start_advance(world.bread, 1, world.baker)  # no estimate and no orders yet: nothing may be made ahead
    first = services.start_advance(world.bread, 5, world.baker, estimate=100)  # 10% of 100 a month is 10
    assert first.origin == "advance" and first.quantity == 5
    with pytest.raises(services.MarketError, match="up to 5"):
        services.start_advance(world.bread, 6, world.baker, estimate=100)
    assert services.start_advance(world.bread, 5, world.baker, estimate=100)


def test_the_advance_limit_later_follows_the_last_three_months_of_orders(world):
    Offer.objects.filter(pk=world.bread.pk).update(created_at=timezone.now() - timedelta(days=200))
    world.bread.refresh_from_db()
    services.place_order(world.buyer(uniq=50), world.bread, D(90))  # 90 over 3 months: 30 a month
    assert services.allowed_advance(world.bread) == D(3)
    with pytest.raises(services.MarketError):
        services.start_advance(world.bread, 4, world.baker)
    assert services.start_advance(world.bread, 3, world.baker)


def test_only_a_worker_can_make_ahead(world):
    stranger = world.buyer("s@x.org")
    with pytest.raises(services.MarketError, match="work in this unit"):
        services.start_advance(world.bread, 1, stranger, estimate=100)
    with pytest.raises(services.MarketError, match="work in this unit"):
        services.start_own_initiative(world.bread, 5, stranger)


# --- own initiative: paid only as the products sell ---


def own_initiative_lot(world, quantity=10, minutes=60):
    po = services.start_own_initiative(world.bread, quantity, world.baker)
    entry = services.record_production_hours(world.baker, po, date.today(), minutes)
    services.start_production(po, world.baker)
    services.complete_production(po, world.baker, quantity)
    return po, entry, StockLot.objects.get(production_order=po)


def test_own_initiative_hours_are_approved_but_not_paid(world):
    po, entry, lot = own_initiative_lot(world)
    entry.refresh_from_db()
    assert po.origin == "own_initiative" and entry.activity == "own_initiative"
    assert entry.status == "pending_sale" and entry.transaction_id is None
    assert lot.origin == "own_initiative" and lot.quantity == 10
    assert ledger.balance(ledger.member_account(world.baker)) == 0


def test_own_initiative_hours_are_paid_only_as_units_sell(world):
    po, entry, lot = own_initiative_lot(world)
    account = ledger.member_account(world.baker)
    rate = ledger.current_period().tax_rate
    services.draw_stock(lot, D(2))  # 2 of 10 sold: a fifth of the hour
    entry.refresh_from_db()
    assert entry.status == "pending_sale" and entry.paid_fraction == D("0.2")
    assert ledger.balance(account) == D("0.2") - D("0.2") * rate
    services.draw_stock(lot, D(8))
    entry.refresh_from_db()
    assert entry.status == "paid" and entry.paid_fraction == 1
    assert ledger.balance(account) == D(1) - D(1) * rate


def test_the_rounding_remainder_is_paid_when_the_lot_is_sold_out(world):
    po, entry, lot = own_initiative_lot(world, quantity=3)
    for _ in range(3):
        services.draw_stock(lot, D(1))
    entry.refresh_from_db()
    mine = ledger.Entry.objects.filter(
        transaction__kind="hours_pay", amount__gt=0, account=ledger.member_account(world.baker)
    )
    gross = sum(e.amount for e in mine)
    assert entry.status == "paid" and gross == D(1)  # 0.3333 + 0.3333 + 0.3334


def test_unsold_own_initiative_hours_stay_unpaid_and_the_unit_is_told(world):
    po, entry, lot = own_initiative_lot(world)
    services.draw_stock(lot, D(1))
    mail.outbox.clear()
    with freeze_time(timezone.now() + timedelta(days=6)):
        services.write_off_lots()
    entry.refresh_from_db()
    assert entry.status == "pending_sale" and entry.paid_fraction == D("0.1")
    assert any("written off" in m.subject for m in mail.outbox)


def test_a_made_ahead_batch_pays_its_hours_at_once(world):
    po = services.start_advance(world.bread, 5, world.baker, estimate=100)
    entry = services.record_production_hours(world.baker, po, date.today(), 60)
    entry = HoursEntry.objects.get(pk=entry.pk)
    assert entry.activity == "order" and entry.status == "paid"
