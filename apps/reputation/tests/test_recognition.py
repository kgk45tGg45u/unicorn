from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.catalogue import services as catalogue
from apps.core.hooks import RECOGNITION_HOOK
from apps.ledger.models import Transaction
from apps.market import needs
from apps.market.models import Review
from apps.market.tests.conftest import World, unit_for
from apps.market.tests.test_reviews import delivered_line
from apps.reputation import services
from apps.reputation.models import Recognition
from apps.tickets import flags
from apps.units import services as unit_services

from .conftest import make_member

pytestmark = pytest.mark.django_db

D = Decimal


def make_offer(maker, slug, item, **kw):
    unit = unit_for(maker, slug)
    return catalogue.create_offer(maker, unit, item, batch_size=D(10), direct_minutes_per_batch=300, **kw)


def test_publishing_the_first_offer_for_an_item_creates_first_maker_for_the_unit_and_its_workers():
    maker = make_member("bee@x.org", "Bee")
    mate = make_member("mate@x.org", "Mate")
    item = catalogue.create_item("Honey", "product", "kg")
    offer = make_offer(maker, "bees", item)
    unit_services.decide_join(unit_services.request_to_join(offer.unit, mate), maker, True)
    catalogue.publish_offer(offer, maker)
    rows = Recognition.objects.filter(kind="first_maker", item=item)
    assert rows.filter(member__isnull=True, unit=offer.unit).count() == 1
    assert {r.member for r in rows.exclude(member__isnull=True)} == {maker, mate}
    # a second unit making the same item is not the first maker
    rival_maker = make_member("rival@x.org", "Rival")
    catalogue.publish_offer(make_offer(rival_maker, "rival-bees", item), rival_maker)
    assert rows.filter(member__isnull=True).count() == 1


def test_a_wanted_item_creates_filled_need():
    waiting = make_member("waiting@x.org", "Waiting")
    item = catalogue.create_item("Honey", "product", "kg")
    needs.join_waiting_list(waiting, item, 2)
    maker = make_member("bee@x.org", "Bee")
    offer = make_offer(maker, "bees", item)
    catalogue.publish_offer(offer, maker)
    kinds = set(Recognition.objects.filter(unit=offer.unit, member__isnull=True).values_list("kind", flat=True))
    assert kinds == {"first_maker", "filled_need"}
    assert Recognition.objects.filter(kind="filled_need", member=maker).exists()


def test_an_ordinary_offer_of_a_known_item_is_not_a_filled_need():
    first = make_member("first@x.org", "First")
    item = catalogue.create_item("Bread", "product", "kg")
    catalogue.publish_offer(make_offer(first, "bakery-one", item), first)
    second = make_member("second@x.org", "Second")
    catalogue.publish_offer(make_offer(second, "bakery-two", item), second)
    assert not Recognition.objects.filter(unit__slug="bakery-two").exists()


def test_thanks_appear_on_the_unit_page_can_be_flagged_and_can_be_hidden_by_the_worker(client):
    world = World()
    buyer, line = delivered_line(world)
    from apps.market import services as market

    review = market.write_review(buyer, order_line=line, stars=5, text="The best bread " + "x" * 300, as_thanks=True)
    unit = review.offer.unit
    shown = Recognition.objects.get(kind="thanks", unit=unit, member__isnull=True)
    assert shown.from_member == buyer and shown.review == review and len(shown.text) == 280
    assert [r for r in services.unit_recognitions(unit) if r.kind == "thanks"] == [shown]
    client.force_login(buyer.user)
    page = client.get(f"/units/{unit.slug}/").content.decode()
    assert "Thanks for" in page and "The best bread" in page and 'value="thanks"' in page
    # flagged like any content: enough different members hide it from the unit page
    from apps.rules.services import get_param

    for i in range(get_param("governance.flags.hide_after_flags")):
        flags.flag(make_member(f"f{i}@x.org", f"F{i}"), "thanks", shown.pk, "other")
    assert [r for r in services.unit_recognitions(unit) if r.kind == "thanks"] == []
    # a worker hides their own copy from their portfolio
    worker = world.baker
    mine = Recognition.objects.get(kind="thanks", member=worker)
    client.force_login(worker.user)
    assert "The best bread" in client.get("/portfolio/").content.decode()
    client.post(f"/me/recognition/{mine.pk}/hide/")
    mine.refresh_from_db()
    assert mine.hidden_by_owner
    with pytest.raises(ValueError, match="not yours"):
        services.set_hidden(buyer, mine, False)
    assert Review.objects.count() == 1


def test_hf02_recognition_pays_nothing():
    """Creating each kind of recognition posts no ledger transaction."""
    world = World()
    buyer, line = delivered_line(world)
    from apps.market import services as market

    before = Transaction.objects.count()
    review = market.write_review(buyer, order_line=line, stars=5, text="Thanks", as_thanks=True)
    item = catalogue.create_item("Honey", "product", "kg")
    maker = make_member("bee@x.org", "Bee")
    offer = make_offer(maker, "bees", item)
    after_review = Transaction.objects.count()
    catalogue.publish_offer(offer, maker)  # first_maker
    RECOGNITION_HOOK(maker, "filled_need", item)
    RECOGNITION_HOOK(buyer, "thanks", Review.objects.get(pk=review.pk))
    kinds = set(Recognition.objects.values_list("kind", flat=True))
    assert kinds == {"first_maker", "filled_need", "thanks"}
    assert Transaction.objects.count() == after_review == before


def test_there_is_no_ranking_page():
    from django.urls import NoReverseMatch, reverse

    for name in ("reputation:top", "reputation:ranking", "reputation:leaderboard"):
        with pytest.raises(NoReverseMatch):
            reverse(name)
    assert timezone.now() - timedelta(0) <= timezone.now()
