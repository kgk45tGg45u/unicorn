from decimal import Decimal

import pytest
from django.utils import timezone

from apps.outside import statement
from apps.tradefund import public

pytestmark = pytest.mark.django_db
D = Decimal


def test_the_statement_totals_equal_the_invoices_and_set_asides(shop):
    invoices = [shop.pay(shop.order(q)) for q in (1, 2, 3)]
    ext = statement.extension(shop.baker, timezone.localdate().year)
    assert len(ext["invoices"]) == 3
    row = ext["by_currency"]["EUR"]
    assert row["total"] == sum((i.total for i in invoices), D(0))
    assert row["tax_reserve"] == sum((i.tax_reserve for i in invoices), D(0))
    assert row["setaside"] == sum((i.setaside for i in invoices), D(0))
    assert ext["total_eur"] == row["total"]


def test_refunded_invoices_are_listed_but_not_counted(shop):
    from apps.outside import services

    order = shop.order(1)
    shop.pay(order)
    keep = shop.pay(shop.order(2))
    services.refund_order(order, shop.baker, "Withdrawn")
    ext = statement.extension(shop.baker, timezone.localdate().year)
    assert len(ext["invoices"]) == 2 and ext["by_currency"]["EUR"]["total"] == keep.total


def test_the_statement_extension_is_registered(shop):
    statement.register()
    assert statement.extension in public.STATEMENT_EXTENSIONS
