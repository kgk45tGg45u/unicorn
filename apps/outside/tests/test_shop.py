from decimal import Decimal

import pytest
from django.core import mail

from apps.core.models import AuditEvent
from apps.ledger.models import Entry, Transaction
from apps.members import crypto
from apps.outside import services
from apps.outside.models import OutsideCustomer

pytestmark = pytest.mark.django_db
D = Decimal


def test_the_shop_shows_only_offers_sold_outside(shop):
    assert services.shop_offers() == [shop.bread]
    shop.mill.refresh_from_db()
    assert shop.mill not in services.shop_offers()


def test_an_outside_order_stores_the_euro_price_and_the_seller(shop):
    order = shop.order(2)
    line = order.lines.get()
    assert order.kind == "outside" and order.buyer is None
    assert line.price_eur == D("5.00") and line.currency == "EUR" and line.seller == shop.baker
    assert services.total_of(line) == D("10.00")
    assert line.value_at_order == shop.bread.value_total * 2
    assert order.paid_at is None


def test_the_customer_details_are_stored_encrypted_and_mailed(shop):
    order = shop.order(1)
    customer = order.outside_customer
    assert b"Cora" not in bytes(customer.name_enc)
    assert crypto.system_decrypt(customer.name_enc) == b"Cora Customer"
    assert len(mail.outbox) == 1 and "O-" in mail.outbox[0].subject
    assert "DE89" in mail.outbox[0].body  # the seller's account number is shown with their consent


def test_checkout_needs_the_ticks_and_the_details(shop):
    with pytest.raises(services.OutsideError, match="consumer information"):
        services.place_outside_order(shop.bread, 1, "C", "c@x.org", "A", "DE", False, True)
    with pytest.raises(services.OutsideError, match="privacy"):
        services.place_outside_order(shop.bread, 1, "C", "c@x.org", "A", "DE", True, False)
    with pytest.raises(services.OutsideError, match="email"):
        services.place_outside_order(shop.bread, 1, "C", "nope", "A", "DE", True, True)
    with pytest.raises(services.OutsideError, match="how many"):
        services.place_outside_order(shop.bread, 0, "C", "c@x.org", "A", "DE", True, True)
    assert OutsideCustomer.objects.count() == 0


def test_hf04_outside_orders_never_touch_uniq(shop):
    before = (Transaction.objects.count(), Entry.objects.count())
    order = shop.order(2)
    shop.pay(order)
    assert (Transaction.objects.count(), Entry.objects.count()) == before
    line = order.lines.get()
    assert line.price_uniq == 0 and line.total_uniq == 0


def test_the_shop_pages_work_without_a_login(shop, client):
    assert client.get("/shop/").status_code == 200
    assert shop.bread.item.name.encode() in client.get("/shop/").content
    assert client.get("/shop/consumer-information/").status_code == 200
    assert client.get(f"/shop/offer/{shop.bread.pk}/").status_code == 200
    response = client.post(
        f"/shop/offer/{shop.bread.pk}/",
        {
            "quantity": "1",
            "name": "Cora",
            "email": "c@x.org",
            "address": "Street 1",
            "country": "de",
            "read_info": "on",
            "consent": "on",
        },
    )
    assert response.status_code == 302
    page = client.get(response["Location"])
    assert page.status_code == 200 and b"O-" in page.content
    assert AuditEvent.objects.filter(verb="outside.order_placed").exists()


def test_a_stranger_cannot_open_an_order_page_without_the_token(shop, client):
    assert client.get("/shop/order/not-a-token/").status_code == 404
