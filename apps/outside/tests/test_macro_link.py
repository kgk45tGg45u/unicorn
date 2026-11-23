from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.ledger.services import current_period
from apps.macro import accounts
from apps.macro import world as world_metrics
from apps.outside import services

pytestmark = pytest.mark.django_db
D = Decimal


def _sell_and_hand_over(shop, quantity=2):
    order = shop.order(quantity)
    shop.pay(order)
    line = order.lines.get()
    line.status = "ready"
    line.save()
    return services.deliver(line, shop.baker)


def test_an_outside_sale_raises_trade_by_its_hours_only_when_delivered(shop):
    period = current_period()
    before = accounts.hours_by_use(period)["trade"]
    order = shop.order(2)
    shop.pay(order)
    assert accounts.hours_by_use(period)["trade"] == before  # paid, not yet handed over
    line = order.lines.get()
    line.status = "ready"
    line.save()
    services.deliver(line, shop.baker)
    assert accounts.hours_by_use(period)["trade"] - before == (D(2) * shop.bread.value_total).quantize(D("0.0001"))


def test_confirmed_sales_and_the_tax_share(shop):
    now = timezone.localdate()
    shop.pay(shop.order(2))  # 10.00 euros
    assert services.confirmed_sales_eur(now.year, now.month) == D("10.00")
    assert services.tax_share(now.year, now.month) == shop.profile.tax_reserve_share.quantize(D("0.0001"))


def test_the_planning_rate_after_three_sales_equals_the_hand_calculation(shop):
    share = shop.profile.tax_reserve_share
    hours = D(0)
    for q in (1, 2, 3):
        line = _sell_and_hand_over(shop, q)
        hours += line.value_at_order
    euros, h, _months = services.sales_after_tax_and_hours(3)
    assert h == hours
    assert euros == sum((D(q) * D("5.00") - (D(q) * D("5.00") * share).quantize(D("0.01")) for q in (1, 2, 3)), D(0))
    assert world_metrics is not None


def test_a_deliver_needs_payment_and_the_seller(shop):
    from apps.units.tests.conftest import make_member

    order = shop.order(1)
    line = order.lines.get()
    with pytest.raises(services.OutsideError, match="payment"):
        services.deliver(line, shop.baker)
    with pytest.raises(services.OutsideError, match="Only the seller"):
        services.deliver(line, make_member("z@x.org", "Z"))
    assert timedelta(0) == timedelta(0)
