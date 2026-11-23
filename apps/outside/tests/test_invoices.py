from decimal import Decimal

import pytest
from django.utils import timezone

from apps.outside import invoices
from apps.outside.models import Invoice
from apps.tickets.models import Notification

pytestmark = pytest.mark.django_db
D = Decimal


def test_numbering_is_gap_free_per_seller(shop):
    numbers = [shop.pay(shop.order(1)).number for _ in range(3)]
    year = timezone.localdate().year
    prefix = f"{shop.baker.number}-{year}-"
    assert numbers == [f"{prefix}0001", f"{prefix}0002", f"{prefix}0003"]


def test_the_vat_note_follows_the_small_business_setting(shop):
    assert "§ 19 UStG" in shop.pay(shop.order(1)).vat_note
    shop.profile.small_business = False
    shop.profile.vat_id = "DE123456789"
    shop.profile.save()
    note = shop.pay(shop.order(1)).vat_note
    assert "§ 19" not in note and "19" in note and "DE123456789" in note


def test_the_invoice_keeps_its_own_copy_of_the_customer(shop):
    invoice = shop.pay(shop.order(1))
    assert "Cora Customer" in invoices.customer_of(invoice)
    assert invoice.keep_until.year == invoice.issued_on.year + 8
    assert invoice.lines[0]["item"] == "Bread"


def test_the_turnover_warning_triggers_at_eighty_percent(shop):
    shop.bread.outside_price = D("1000.00")
    shop.bread.save()
    for _ in range(3):  # 3 x 20 x 1000 = 60,000 (below 80,000)
        shop.pay(shop.order(20))
    assert not Notification.objects.filter(member=shop.baker, text__icontains="small-business").exists()
    shop.pay(shop.order(20))  # 80,000 reached
    assert Notification.objects.filter(member=shop.baker, text__icontains="small-business").count() == 1
    shop.pay(shop.order(1))  # told once a year
    assert Notification.objects.filter(member=shop.baker, text__icontains="small-business").count() == 1


def test_invoice_pages_for_customer_and_seller(shop, client):
    order = shop.order(1)
    invoice = shop.pay(order)
    page = client.get(f"/shop/order/{order.public_token}/invoice/")
    assert page.status_code == 200 and invoice.number.encode() in page.content
    assert client.get(f"/shop/seller/invoice/{invoice.pk}/").status_code in (302, 403)  # login needed
    assert Invoice.objects.count() == 1
