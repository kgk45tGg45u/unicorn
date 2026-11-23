"""Phase 10 acceptance: the woodshop sells an oak chair for 180 euros."""

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.catalogue import services as cat
from apps.ledger.models import Entry
from apps.ledger.services import current_period
from apps.macro import accounts
from apps.market.tests.conftest import unit_for
from apps.outside import services
from apps.outside.tests.conftest import IBAN
from apps.tradefund import services as fund
from apps.units.tests.conftest import make_member

pytestmark = pytest.mark.django_db
D = Decimal


def test_an_oak_chair_goes_from_order_to_invoice_to_trade_hours():
    maker = make_member("wood@x.org", "Wood")
    unit = unit_for(maker, "woodshop")
    chair_item = cat.create_item("Oak chair", "product", "pc")
    chair = cat.create_offer(
        maker, unit, chair_item, batch_size=D(1), cycle_days=1, direct_minutes_per_batch=258
    )  # 4.30 hours
    cat.publish_offer(chair, maker)
    cat.recompute_values()
    chair.refresh_from_db()
    fund.become_holder(maker, "EUR", IBAN)
    profile = services.activate_seller(maker, "Wood Works", "Oak Street 1", small_business=True, share=D("0.15"))
    services.apply_outside_offer(chair, "180.00", "EUR", maker)
    entries_before = Entry.objects.count()

    order = services.place_outside_order(chair, 1, "Cora", "c@x.org", "Street 5", "DE", True, True)
    invoice = services.confirm_customer_payment(order, maker, "180.00")
    assert "§ 19" in invoice.vat_note
    assert invoice.tax_reserve == D("27.00") and invoice.setaside == D("153.00")

    line = order.lines.get()
    line.status = "ready"
    line.save()
    services.deliver(line, maker)
    assert accounts.hours_by_use(current_period())["trade"] == D("4.3000")
    assert Entry.objects.count() == entries_before  # HF-4: no UNIQ moved
    assert services.confirmed_sales_eur(timezone.localdate().year, timezone.localdate().month) == D("180.00")
    assert profile.pk
