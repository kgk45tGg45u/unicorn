import pytest

from apps.catalogue import services as cat
from apps.core.models import AuditEvent
from apps.outside import services
from apps.outside.models import SellerProfile
from apps.outside.tests.conftest import IBAN, Shop
from apps.tradefund import services as fund
from apps.units.tests.conftest import make_member

pytestmark = pytest.mark.django_db


def test_activating_without_being_a_holder_is_refused(world):
    with pytest.raises(services.OutsideError, match="holder"):
        services.activate_seller(world.baker, "Baker", "Street 1")


def test_activating_needs_a_verified_member():
    stranger = make_member("n@x.org", "New", verified=False)
    with pytest.raises(services.OutsideError, match="verified"):
        services.activate_seller(stranger, "New", "Street 1")


def test_a_holder_can_become_a_seller_and_signs_the_contract(world):
    fund.become_holder(world.baker, "EUR", IBAN)
    profile = services.activate_seller(world.baker, "Baker Bakery", "Mill Road 1")
    assert profile.active and profile.small_business
    assert profile.tax_reserve_share > 0
    assert world.baker.signatures.filter(template__kind="outside_seller").exists()
    assert AuditEvent.objects.filter(verb="seller.activated").exists()


def test_invoice_name_and_address_are_needed(world):
    fund.become_holder(world.baker, "EUR", IBAN)
    with pytest.raises(services.OutsideError, match="address"):
        services.activate_seller(world.baker, "Baker", " ")


def test_changing_the_tax_reserve_needs_a_reason_that_is_kept(shop):
    with pytest.raises(services.OutsideError, match="reason"):
        services.change_tax_reserve(shop.baker, "0.2", " ")
    services.change_tax_reserve(shop.baker, "0.2", "My adviser says so")
    shop.profile.refresh_from_db()
    assert str(shop.profile.tax_reserve_share) == "0.2000"
    event = AuditEvent.objects.get(verb="seller.tax_reserve_changed")
    assert event.data["reason"] == "My adviser says so"


def test_an_offer_is_sold_outside_only_with_a_seller_of_record(world):
    other = make_member("o@x.org", "Other")
    with pytest.raises(services.OutsideError, match="seller of record"):
        services.apply_outside_offer(world.bread, "5.00", "EUR", other)
    fund.become_holder(world.baker, "EUR", IBAN)
    services.activate_seller(world.baker, "Baker", "Street 1")
    services.apply_outside_offer(world.bread, "5.00", "EUR", world.baker)
    world.bread.refresh_from_db()
    assert world.bread.sold_outside and world.bread.outside_seller == world.baker


def test_hf03_the_uniq_price_is_untouched_by_an_outside_price(shop):
    before = shop.bread.price_uniq if hasattr(shop.bread, "price_uniq") else shop.bread.value_total
    services.apply_outside_offer(shop.bread, "9.00", "EUR", shop.baker)
    shop.bread.refresh_from_db()
    after = shop.bread.price_uniq if hasattr(shop.bread, "price_uniq") else shop.bread.value_total
    assert before == after


def test_the_council_decides_by_a_decision_and_a_one_person_unit_directly(world):
    fund.become_holder(world.baker, "EUR", IBAN)
    services.activate_seller(world.baker, "Baker", "Street 1")
    result = services.propose_outside_offer(world.baker, world.bread, "6.00", "EUR", world.baker)
    world.bread.refresh_from_db()
    assert world.bread.sold_outside and result == world.bread


def test_only_products_are_sold_outside(shop):
    item = cat.create_item("Haircut", "service", "h")
    offer = cat.create_offer(shop.baker, shop.bakery_unit, item, duration_minutes=60, capacity=1)
    with pytest.raises(services.OutsideError, match="products"):
        services.apply_outside_offer(offer, "20.00", "EUR", shop.baker)


def test_the_shop_needs_an_active_seller(shop):
    assert Shop is not None
    assert shop.bread in services.shop_offers()
    SellerProfile.objects.update(active=False)
    assert services.shop_offers() == []
