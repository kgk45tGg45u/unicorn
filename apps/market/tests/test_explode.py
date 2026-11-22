from datetime import date
from decimal import Decimal

import pytest

from apps.catalogue import services as cat
from apps.core.models import AuditEvent
from apps.ledger.models import Transaction
from apps.market import services
from apps.market.models import InputRequest, ProductionOrder, PurchaseNeed
from apps.market.tests.conftest import unit_for
from apps.units.tests.conftest import make_member

pytestmark = pytest.mark.django_db
D = Decimal


def test_an_order_for_bread_creates_a_flour_request_at_the_mill_and_a_mill_batch(world):
    line = services.place_order(world.buyer(), world.bread, D(2))
    request = InputRequest.objects.get(item__name="Flour")
    assert request.quantity == D("1.2")  # 24 kg for 40 loaves: 1.2 kg for 2
    assert request.source == "unicorn" and request.supplier_offer == world.mill
    assert request.production_order == line.production_order
    child = request.child_production_order
    assert child.offer == world.mill and child.origin == "input_request" and child.quantity == D("1.2")
    assert child.status == "open"
    assert request.due_date < line.production_order.due_date  # the flour comes first


def test_salt_goes_to_a_purchase_need(world):
    services.place_order(world.buyer(), world.bread, D(2))
    need = PurchaseNeed.objects.get()
    assert need.item.name == "Salt" and need.unit == world.bakery_unit and need.status == "open"
    assert need.quantity == D("0.025") and need.euro_estimate == D("0.02")  # 0.025 kg at 0.60 a kg
    assert need.month == date.today().replace(day=1) or need.month.day == 1


def test_more_orders_add_only_what_is_missing(world):
    a, b = world.buyer("a@x.org"), world.buyer("b@x.org")
    services.place_order(a, world.bread, D(2))
    services.place_order(b, world.bread, D(2))
    assert InputRequest.objects.filter(item__name="Flour").count() == 2
    flour = sum(r.quantity for r in InputRequest.objects.filter(item__name="Flour"))
    assert flour == D("2.4")
    assert PurchaseNeed.objects.get().quantity == D("0.05")
    assert ProductionOrder.objects.filter(offer=world.mill).count() == 1  # both requests share the mill's batch
    assert ProductionOrder.objects.get(offer=world.mill).quantity == D("2.4")


def test_an_own_free_input_waits_for_its_provider(world):
    giver = make_member("giver@x.org", "Giver")
    cat.add_input(world.baker, world.bread, "Garden herbs", "kg", D(2), "own_free", provided_by=giver)
    services.place_order(world.buyer(), world.bread, D(4))
    request = InputRequest.objects.get(item__name="Garden herbs")
    assert request.status == "open" and request.provided_by == giver and request.quantity == D("0.2")
    with pytest.raises(services.MarketError, match="provides this input"):
        services.confirm_input(request, world.baker)
    services.confirm_input(request, giver)
    request.refresh_from_db()
    assert request.status == "confirmed"
    services.mark_received(request, world.baker)
    request.refresh_from_db()
    assert request.status == "received"


def test_hf05_units_exchange_no_uniq(world):
    buyer = world.buyer()
    before = Transaction.objects.count()  # funding the buyer is a transaction; the chain adds none
    line = services.place_order(buyer, world.bread, D(5))
    request = InputRequest.objects.get(item__name="Flour")
    mill_po = request.child_production_order
    services.start_production(mill_po, world.miller)
    services.complete_production(mill_po, world.miller, D("1.5"))
    services.mark_delivered(request, world.miller)
    services.mark_received(request, world.baker)
    services.start_production(line.production_order, world.baker)
    services.complete_production(line.production_order, world.baker, 5)
    assert Transaction.objects.count() == before
    assert before >= 1


def test_delivery_between_units_is_recorded_and_guarded(world):
    services.place_order(world.buyer(), world.bread, D(2))
    request = InputRequest.objects.get(item__name="Flour")
    with pytest.raises(services.MarketError, match="not been handed over"):
        services.mark_received(request, world.baker)
    with pytest.raises(services.MarketError, match="work in this unit"):
        services.mark_delivered(request, world.baker)  # only the mill's workers hand flour over
    services.mark_delivered(request, world.miller)
    with pytest.raises(services.MarketError, match="work in this unit"):
        services.mark_received(request, world.miller)  # only the bakery's workers receive it
    services.mark_received(request, world.baker)
    request.refresh_from_db()
    assert request.status == "received" and request.delivered_at and request.received_at
    verbs = set(AuditEvent.objects.values_list("verb", flat=True))
    assert {"input.delivered", "input.received"} <= verbs


def test_the_supplier_is_the_preferred_one_then_the_same_town_then_the_quietest(world):
    rival_miller = make_member("rival@x.org", "Rival")
    town_unit = unit_for(rival_miller, "town-mill", town="Leipzig")
    world.bakery_unit.town = "Leipzig"
    world.bakery_unit.save()
    flour = world.mill.item
    near = cat.create_offer(
        rival_miller, town_unit, flour, batch_size=D(100), cycle_days=1, direct_minutes_per_batch=300
    )
    cat.publish_offer(near, rival_miller)
    services.place_order(world.buyer(), world.bread, D(2))
    assert InputRequest.objects.get(item__name="Flour").supplier_offer == near  # same town beats the lower id
    # a preferred supplier beats the town
    row = world.bread.inputs.get(item=flour)
    row.preferred_supplier = world.mill
    row.save()
    services.place_order(world.buyer("b@x.org"), world.bread, D(2))
    assert InputRequest.objects.filter(item__name="Flour").order_by("-id").first().supplier_offer == world.mill


def test_cancelling_the_order_gives_the_inputs_back(world):
    buyer = world.buyer()
    line = services.place_order(buyer, world.bread, D(2))
    request = InputRequest.objects.get(item__name="Flour")
    services.cancel_line(line, buyer)
    request.refresh_from_db()
    assert request.status == "cancelled"
    assert request.child_production_order.status == "cancelled"
    assert InputRequest.objects.get(item__name="Salt").status == "cancelled"
    assert PurchaseNeed.objects.get().quantity == 0


def test_a_chain_that_is_too_deep_stops_and_is_noted(world):
    offers = []
    items = [cat.create_item(f"Part {i}", "product", "pc") for i in range(12)]
    for i in reversed(range(12)):
        unit = unit_for(make_member(f"p{i}@x.org", f"P{i}"), f"part-{i}")
        owner = unit.memberships.first().member
        offer = cat.create_offer(owner, unit, items[i], batch_size=D(1), direct_minutes_per_batch=6)
        if i < 11:
            cat.add_input(owner, offer, f"Part {i + 1}", "pc", D(1), "unicorn")
        cat.publish_offer(offer, owner)
        offers.append(offer)
    cat.recompute_values()
    top = offers[-1]
    top.refresh_from_db()
    buyer = world.buyer()
    services.place_order(buyer, top, D(1))
    assert ProductionOrder.objects.filter(offer__item__name__startswith="Part ").count() == 11
    assert AuditEvent.objects.filter(verb="input chain too deep").exists()
