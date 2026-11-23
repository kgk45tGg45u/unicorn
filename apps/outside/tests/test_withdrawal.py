from datetime import timedelta

import pytest
from django.utils import timezone

from apps.outside import services
from apps.tickets.models import Notification

pytestmark = pytest.mark.django_db


def test_a_withdrawal_within_fourteen_days_tells_the_seller(shop):
    order = shop.order(1)
    services.request_withdrawal(order)
    order.refresh_from_db()
    assert order.withdrawn_at is not None
    assert Notification.objects.filter(member=shop.baker, text__icontains="withdrew").exists()
    with pytest.raises(services.OutsideError, match="already"):
        services.request_withdrawal(order)


def test_after_fourteen_days_the_period_has_ended(shop):
    order = shop.order(1)
    later = timezone.now() + timedelta(days=15)
    assert not services.withdrawal_open(order, later)
    with pytest.raises(services.OutsideError, match="14 days"):
        services.request_withdrawal(order, later)


def test_the_withdrawal_page_explains_the_period(shop, client):
    order = shop.order(1)
    page = client.get(f"/shop/order/{order.public_token}/withdraw/")
    assert page.status_code == 200 and b"DRAFT" in page.content
    assert client.get("/shop/consumer-information/").content.count(b"DRAFT") >= 1
    client.post(f"/shop/order/{order.public_token}/withdraw/")
    order.refresh_from_db()
    assert order.withdrawn_at is not None


def test_contact_details_are_wiped_ninety_days_after_delivery(shop):
    order = shop.order(1)
    shop.pay(order)
    line = order.lines.get()
    line.status = "ready"
    line.save()
    services.deliver(line, shop.baker)
    customer = order.outside_customer
    customer.refresh_from_db()
    assert services.wipe_contacts(timezone.now() + timedelta(days=89)) == 0
    assert services.wipe_contacts(timezone.now() + timedelta(days=91)) == 1
    customer.refresh_from_db()
    assert bytes(customer.email_enc) == b"" and customer.wiped_at is not None
    assert services.wipe_contacts(timezone.now() + timedelta(days=92)) == 0
