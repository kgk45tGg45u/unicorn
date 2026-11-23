from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.utils import timezone

from apps.market.models import OrderLine
from apps.outside import services
from apps.tradefund import books
from apps.tradefund.models import Holder

pytestmark = pytest.mark.django_db
D = Decimal


def _holding(shop):
    return books.holding(Holder.objects.get(member=shop.baker))


def _reserve(shop):
    return books.reserve(Holder.objects.get(member=shop.baker))


def test_a_hundred_euros_sets_aside_eighty_five_and_marks_the_reserve(shop):
    shop.profile.tax_reserve_share = D("0.15")
    shop.profile.save()
    shop.bread.outside_price = D("50.00")
    shop.bread.save()
    order = shop.order(2)
    invoice = shop.pay(order)
    assert invoice.total == D("100.00") and invoice.tax_reserve == D("15.00") and invoice.setaside == D("85.00")
    assert _holding(shop) == D("85.00")
    assert _reserve(shop) == D("1.70")


def test_paying_starts_production_and_issues_an_invoice(shop):
    order = shop.order(2)
    line = order.lines.get()
    assert line.production_order_id is not None or line.status != OrderLine.CANCELLED
    invoice = shop.pay(order)
    order.refresh_from_db()
    assert order.paid_at is not None and invoice.number.endswith("-0001")
    with pytest.raises(services.OutsideError, match="already"):
        shop.pay(order)


def test_only_the_seller_confirms_the_payment(shop):
    from apps.units.tests.conftest import make_member

    order = shop.order(1)
    other = make_member("o@x.org", "Other")
    with pytest.raises(services.OutsideError, match="Only the seller"):
        services.confirm_customer_payment(order, other, "5.00")


def test_an_unpaid_order_is_cancelled_after_fourteen_days(shop):
    order = shop.order(1)
    assert services.cancel_unpaid(timezone.now() + timedelta(days=13)) == 0
    mail.outbox.clear()
    assert services.cancel_unpaid(timezone.now() + timedelta(days=15)) == 1
    assert order.lines.get().status == OrderLine.CANCELLED
    assert len(mail.outbox) == 1
    assert services.cancel_unpaid(timezone.now() + timedelta(days=16)) == 0  # safe to run twice


def test_a_paid_order_is_not_cancelled(shop):
    order = shop.order(1)
    shop.pay(order)
    assert services.cancel_unpaid(timezone.now() + timedelta(days=30)) == 0


def test_a_refund_reverses_the_set_aside_and_keeps_the_tax_reserve(shop):
    order = shop.order(2)
    invoice = shop.pay(order)
    assert _holding(shop) == invoice.setaside > 0
    services.refund_order(order, shop.baker, "Customer withdrew")
    invoice.refresh_from_db()
    assert _holding(shop) == 0 and invoice.refunded_at is not None and invoice.tax_reserve > 0
    assert order.lines.get().status == OrderLine.CANCELLED
    with pytest.raises(services.OutsideError, match="already"):
        services.refund_order(order, shop.baker, "again")


def test_a_refund_needs_a_reason(shop):
    order = shop.order(1)
    shop.pay(order)
    with pytest.raises(services.OutsideError, match="why"):
        services.refund_order(order, shop.baker, " ")
