from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time

from apps.catalogue import services as cat
from apps.core import hooks
from apps.market import services
from apps.market.models import Review
from apps.market.tests.conftest import unit_for
from apps.units.tests.conftest import make_member

pytestmark = pytest.mark.django_db
D = Decimal


def delivered_line(world, buyer=None):
    buyer = buyer or world.buyer()
    line = services.place_order(buyer, world.bread, D(2))
    po = line.production_order
    services.start_production(po, world.baker)
    services.complete_production(po, world.baker, 2)
    services.hand_over(line, world.baker)
    services.confirm_received(line, buyer)
    line.refresh_from_db()
    return buyer, line


def test_only_the_buyer_can_review_and_once(world):
    buyer, line = delivered_line(world)
    other = world.buyer("o@x.org")
    with pytest.raises(services.MarketError, match="yourself"):
        services.write_review(other, order_line=line, stars=5)
    review = services.write_review(buyer, order_line=line, stars=4, text="Good bread")
    assert review.offer == world.bread and review.stars == 4
    with pytest.raises(services.MarketError, match="already reviewed"):
        services.write_review(buyer, order_line=line, stars=5)


def test_a_review_needs_a_delivered_line_and_1_to_5_stars(world):
    buyer, line = delivered_line(world, world.buyer("b@x.org"))
    waiting = services.place_order(buyer, world.bread, D(2))
    with pytest.raises(services.MarketError, match="once you have received"):
        services.write_review(buyer, order_line=waiting, stars=5)
    for bad in (0, 6, "x", None):
        with pytest.raises(services.MarketError, match="1 and 5 stars"):
            services.write_review(buyer, order_line=line, stars=bad)
    with pytest.raises(services.MarketError, match="one order or one booking"):
        services.write_review(buyer, stars=5)


def test_the_database_allows_exactly_one_thing_per_review(world):
    buyer, line = delivered_line(world)
    with pytest.raises(IntegrityError), transaction.atomic():
        Review.objects.create(offer=world.bread, author=buyer, stars=3)  # neither a line nor a booking
    with pytest.raises(IntegrityError), transaction.atomic():
        Review.objects.create(offer=world.bread, order_line=line, author=buyer, stars=9)


def test_a_booking_can_be_reviewed_once_confirmed(salon):
    customer = salon.customer()
    slot = salon.slot()
    booking = services.book(customer, slot)
    with pytest.raises(services.MarketError, match="once you have received"):
        services.write_review(customer, booking=booking, stars=5)
    with freeze_time(timezone.now() + timedelta(days=1, hours=3)):
        services.mark_performed(slot, salon.provider)
    booking.refresh_from_db()
    services.confirm_performed(booking, customer)
    booking.refresh_from_db()
    assert services.write_review(customer, booking=booking, stars=5, text="Lovely").offer == salon.offer


def test_the_thank_you_box_calls_the_recognition_hook(world):
    seen = []
    handler = lambda member, kind, obj: seen.append((member, kind, obj))  # noqa: E731
    hooks.RECOGNITION_HANDLERS.append(handler)
    try:
        buyer, line = delivered_line(world)
        review = services.write_review(buyer, order_line=line, stars=5, text="Thank you!", as_thanks=True)
        assert seen == [(buyer, "thanks", review)] and review.as_thanks
        other, line2 = delivered_line(world, world.buyer("b@x.org"))
        services.write_review(other, order_line=line2, stars=5, text="Thank you!")  # box not ticked
        assert len(seen) == 1
    finally:
        hooks.RECOGNITION_HANDLERS.remove(handler)


def test_a_thank_you_review_is_saved_with_the_recognition_handlers_attached(world):
    buyer, line = delivered_line(world)
    assert services.write_review(buyer, order_line=line, stars=5, text="Thanks", as_thanks=True)


def test_hf10_reviews_do_not_change_order(world):
    """Two bakeries make the same bread. Five-star reviews for the second change neither list order nor prices."""
    rival = make_member("rival@x.org", "Rival")
    rival_offer = cat.create_offer(
        rival, unit_for(rival, "aaa-bakery"), world.bread.item, batch_size=D(40), direct_minutes_per_batch=240
    )
    cat.publish_offer(rival_offer, rival)
    cat.recompute_values()
    before = [o.pk for o in services.search_offers(text="bread")]
    prices = {o.pk: o.value_total for o in services.search_offers(text="bread")}
    assert len(before) == 2

    for n in range(3):
        buyer = world.buyer(f"r{n}@x.org")
        line = services.place_order(buyer, world.bread, D(1))
        po = line.production_order
        services.start_production(po, world.baker)
        services.complete_production(po, world.baker, 1)
        services.hand_over(line, world.baker)
        services.confirm_received(line, buyer)
        services.write_review(buyer, order_line=line, stars=5)
    after = services.search_offers(text="bread")
    assert [o.pk for o in after] == before  # alphabetical by unit name, whatever the stars
    assert {o.pk: o.value_total for o in after} == prices
    assert services.review_summary(world.bread)[0] == 5


def test_the_offer_page_shows_the_average_and_the_latest_ten(world, client):
    for n in range(12):
        buyer, line = delivered_line(world, world.buyer(f"b{n}@x.org"))
        services.write_review(buyer, order_line=line, stars=4 if n % 2 else 5, text=f"Review number {n}")
    page = client.get(reverse("catalogue:offer", args=[world.bread.pk])).content.decode()
    assert "4.5 out of 5 stars from 12 reviews" in page
    assert "Review number 11" in page and "Review number 2" in page and "Review number 1<" not in page
    assert page.count("Review number") == 10


def test_only_the_council_reads_all_reviews(world, client):
    buyer, line = delivered_line(world)
    services.write_review(buyer, order_line=line, stars=3, text="Fine")
    assert len(services.reviews_for_council(world.baker, world.bakery_unit)) == 1
    with pytest.raises(services.MarketError):
        services.reviews_for_council(buyer, world.bakery_unit)
    client.force_login(buyer.user)
    assert client.get(reverse("market:unit_reviews", args=[world.bakery_unit.slug])).status_code == 403
    client.force_login(world.baker.user)
    assert "Fine" in client.get(reverse("market:unit_reviews", args=[world.bakery_unit.slug])).content.decode()
    assert "Read all reviews" in client.get(reverse("catalogue:offer", args=[world.bread.pk])).content.decode()


def test_the_review_form_works_and_belongs_to_the_buyer(world, client):
    buyer, line = delivered_line(world)
    client.force_login(world.baker.user)
    assert client.get(reverse("market:review_line", args=[line.pk])).status_code == 404
    client.force_login(buyer.user)
    assert (
        "Also show my words as a thank-you"
        in client.get(reverse("market:review_line", args=[line.pk])).content.decode()
    )
    response = client.post(reverse("market:review_line", args=[line.pk]), {"stars": "5", "text": "Great"})
    assert response.status_code == 302
    assert Review.objects.get().text == "Great"


def test_search_finds_offers_by_name_kind_and_town(world, salon):
    assert [o.item.name for o in services.search_offers(text="brea")] == ["Bread"]
    assert [o.item.name for o in services.search_offers(kind="service")] == ["Haircut"]
    assert {o.item.name for o in services.search_offers()} == {"Bread", "Flour", "Haircut"}
    world.bakery_unit.town = "Leipzig"
    world.bakery_unit.save()
    assert [o.item.name for o in services.search_offers(town="leipzig")] == ["Bread"]
    assert services.search_offers(text="zzz") == []
