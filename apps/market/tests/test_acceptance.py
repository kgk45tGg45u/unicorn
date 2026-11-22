"""The phase 05 acceptance check: bread, a haircut, a lot that expires, and the needs board."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time

from apps.ledger import services as ledger
from apps.market import services
from apps.market.models import InputRequest, PurchaseNeed, StockLot, WasteRecord
from apps.market.tests.conftest import ServiceWorld, World
from apps.units.models import HoursEntry

pytestmark = pytest.mark.django_db
D = Decimal


def test_the_phase_05_acceptance_check(client):
    world = World()
    salon = ServiceWorld()

    # 1. A member orders 2 loaves: the bakery's batch, the mill's input request and the salt purchase need appear.
    buyer = world.buyer(uniq=10)
    line = services.place_order(buyer, world.bread, D(2))
    batch = line.production_order
    assert batch.offer == world.bread and batch.quantity == 2
    flour = InputRequest.objects.get(item__name="Flour")
    assert flour.supplier_offer == world.mill and flour.child_production_order.offer == world.mill
    assert PurchaseNeed.objects.get().item.name == "Salt"

    # 2. The bakery completes the batch; the member confirms receipt, and Fund 1 receives 0.2850 UNIQ.
    services.mark_delivered(flour, world.miller)
    services.mark_received(flour, world.baker)
    services.start_production(batch, world.baker)
    services.complete_production(batch, world.baker, 2)
    services.hand_over(line, world.baker)
    services.confirm_received(line, buyer)
    assert ledger.balance(ledger.fund1()) == D("0.2850")

    # 3. A haircut is booked, performed and confirmed; the hairdresser's 1-hour entry is paid.
    customer = salon.customer()
    slot = salon.slot()
    booking = services.book(customer, slot)
    with freeze_time(timezone.now() + timedelta(days=1, hours=3)):
        services.mark_performed(slot, salon.provider)
    booking.refresh_from_db()
    services.confirm_performed(booking, customer)
    entry = HoursEntry.objects.get(activity="booking")
    assert entry.minutes == 60 and entry.status == "paid"
    assert ledger.balance(ledger.fund1()) == D("0.2850") + D("1.0000")

    # 4. An advance lot expires and becomes waste.
    po = services.start_advance(world.bread, 5, world.baker, estimate=100)
    services.start_production(po, world.baker)
    services.complete_production(po, world.baker, 5)
    lot = StockLot.objects.get(production_order=po)
    with freeze_time(timezone.now() + timedelta(days=6)):
        assert services.write_off_lots() == 1
    lot.refresh_from_db()
    waste = WasteRecord.objects.get()
    assert lot.status == "written_off" and waste.hours == D(5) * world.bread.value_total

    # 5. The needs board shows salt under "Bought from outside".
    page = client.get(reverse("market:needs")).content.decode()
    assert "Bought from outside" in page and "Salt" in page
    assert page.index("Bought from outside") < page.index("Salt")
