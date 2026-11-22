from datetime import timedelta
from decimal import Decimal

import pytest
from allauth.account.models import EmailAddress
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time

from apps.ledger import services as ledger
from apps.market import services
from apps.market.models import Sale, StockLot

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture
def shop(world):
    """Bread on the shelf: an order that started a batch of 40, completed, with 38 left over."""
    line = services.place_order(world.buyer("first@x.org"), world.bread, D(2))
    po = line.production_order
    services.start_production(po, world.baker)
    services.complete_production(po, world.baker, 40)
    return world


def test_a_sale_is_paid_once_and_draws_the_shelf(shop):
    sale = services.create_sale(shop.baker, shop.bread, 3)
    assert len(sale.code) == 10 and sale.amount_uniq == D("0.4275")
    buyer = shop.buyer("walker@x.org")
    fund1 = ledger.balance(ledger.fund1())
    services.pay_sale(sale.code, buyer)
    sale.refresh_from_db()
    assert sale.status == "paid" and sale.buyer == buyer and sale.paid_at
    assert ledger.balance(ledger.fund1()) - fund1 == D("0.4275")
    assert StockLot.objects.get().quantity_left == 35
    assert ledger.Transaction.objects.filter(kind="purchase").latest("seq").reason == (
        "Bought 3 Bread from Bakery in person"
    )
    with pytest.raises(services.MarketError, match="already been paid"):
        services.pay_sale(sale.code, shop.buyer("second@x.org"))
    assert StockLot.objects.get().quantity_left == 35


def test_an_expired_code_cannot_be_paid(shop):
    sale = services.create_sale(shop.baker, shop.bread, 1)
    buyer = shop.buyer("walker@x.org")
    with freeze_time(timezone.now() + timedelta(minutes=11)):
        assert services.get_sale(sale.code).status == "expired"
        with pytest.raises(services.MarketError, match="expired"):
            services.pay_sale(sale.code, buyer)
    sale.refresh_from_db()
    assert sale.status == "expired" and not ledger.Transaction.objects.filter(kind="purchase").exists()


def test_a_seller_cannot_pay_their_own_sale(shop):
    sale = services.create_sale(shop.baker, shop.bread, 1)
    with pytest.raises(services.MarketError, match="own sale"):
        services.pay_sale(sale.code, shop.baker)


def test_only_a_worker_sells_and_only_what_is_on_the_shelf(shop):
    stranger = shop.buyer("s@x.org")
    with pytest.raises(services.MarketError, match="work in this unit"):
        services.create_sale(stranger, shop.bread, 1)
    with pytest.raises(services.MarketError, match="not enough"):
        services.create_sale(shop.baker, shop.bread, 100)
    with pytest.raises(services.MarketError):
        services.create_sale(shop.baker, shop.bread, 0)


def test_the_buyer_needs_enough_uniq_and_to_be_a_member(shop):
    sale = services.create_sale(shop.baker, shop.bread, 1)
    from apps.market.tests.conftest import fund
    from apps.units.tests.conftest import make_member

    poor = make_member("poor@x.org", "Poor")
    fund(poor, D("0.01"))
    with pytest.raises(services.MarketError, match="Not enough UNIQ"):
        services.pay_sale(sale.code, poor)
    applicant = make_member("app@x.org", "App", verified=False)
    with pytest.raises(services.MarketError, match="Only members"):
        services.pay_sale(sale.code, applicant)
    with pytest.raises(services.MarketError, match="does not exist"):
        services.pay_sale("NOSUCHCODE", poor)


def test_a_sale_cannot_leave_the_shelf_short(shop):
    first = services.create_sale(shop.baker, shop.bread, 30)
    second = services.create_sale(shop.baker, shop.bread, 30)  # both look possible when made
    services.pay_sale(first.code, shop.buyer("a@x.org", uniq=20))
    with pytest.raises(services.MarketError, match="any more"):
        services.pay_sale(second.code, shop.buyer("b@x.org", uniq=20))


def test_the_expiry_job_marks_old_sales(shop):
    services.create_sale(shop.baker, shop.bread, 1)
    with freeze_time(timezone.now() + timedelta(minutes=30)):
        assert services.expire_sales() == 1
    assert Sale.objects.get().status == "expired"


# --- the pages ---


def test_the_seller_sees_a_qr_code_and_the_buyer_can_pay(shop, client):
    client.force_login(shop.baker.user)
    page = client.get(reverse("market:sell")).content.decode()
    assert "Bread" in page
    response = client.post(reverse("market:sell"), {"offer": shop.bread.pk, "quantity": "2"})
    sale = Sale.objects.get()
    assert response.status_code == 302 and response["Location"] == reverse("market:sale", args=[sale.code])
    shown = client.get(reverse("market:sale", args=[sale.code])).content.decode()
    assert "<svg" in shown and f"/pay/{sale.code}/" in shown

    buyer = shop.buyer("walker@x.org")
    client.force_login(buyer.user)
    page = client.get(reverse("market:pay", args=[sale.code])).content.decode()
    assert "0.29 UNIQ" in page and "Bakery" in page
    client.post(reverse("market:pay", args=[sale.code]))
    sale.refresh_from_db()
    assert sale.status == "paid"
    assert "has been paid" in client.get(reverse("market:pay", args=[sale.code])).content.decode()


def test_a_big_payment_asks_for_a_recent_sign_in(shop, client):
    """Above 10 UNIQ the buyer must have signed in again just now (HF-13, docs/08 section 3)."""
    shop.bread.item.shelf_life_days = None
    shop.bread.item.save()
    big = Sale.objects.create(
        offer=shop.bread,
        quantity=D(2),
        seller=shop.baker,
        code="BIGBIGBIG1",
        amount_uniq=D(11),
        expires_at=timezone.now() + timedelta(minutes=5),
    )
    buyer = shop.buyer("rich@x.org", uniq=50)
    EmailAddress.objects.create(user=buyer.user, email="rich@x.org", verified=True, primary=True)
    client.force_login(buyer.user)
    response = client.get(reverse("market:pay", args=[big.code]))
    assert response.status_code == 302 and "reauthenticate" in response["Location"]
    small = Sale.objects.create(
        offer=shop.bread,
        quantity=D(2),
        seller=shop.baker,
        code="SMALLSMALL",
        amount_uniq=D(5),
        expires_at=timezone.now() + timedelta(minutes=5),
    )
    assert client.get(reverse("market:pay", args=[small.code])).status_code == 200


def test_an_expired_code_shows_a_friendly_message(shop, client):
    sale = services.create_sale(shop.baker, shop.bread, 1)
    client.force_login(shop.buyer("walker@x.org").user)
    with freeze_time(timezone.now() + timedelta(minutes=11)):
        page = client.get(reverse("market:pay", args=[sale.code])).content.decode()
    assert "has expired" in page and "Traceback" not in page


def test_only_the_seller_sees_the_code_page(shop, client):
    sale = services.create_sale(shop.baker, shop.bread, 1)
    client.force_login(shop.buyer("walker@x.org").user)
    assert client.get(reverse("market:sale", args=[sale.code])).status_code == 404
    assert client.get(reverse("market:pay", args=["NOSUCHCODE"])).status_code == 404


def test_the_pages_need_a_login(shop, client):
    assert client.get(reverse("market:sell")).status_code == 302
