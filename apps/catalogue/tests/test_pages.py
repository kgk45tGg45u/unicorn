from decimal import Decimal

import pytest
from django.urls import reverse

from apps.catalogue import services
from apps.catalogue.models import Offer
from apps.units import services as us
from apps.units.tests.conftest import make_member, make_unit

from .test_values import world

pytestmark = pytest.mark.django_db
D = Decimal


def test_the_offer_page_shows_the_direct_and_indirect_split(client):
    m, mill, bake = world()
    services.recompute_values()
    page = client.get(reverse("catalogue:offer", args=[bake.pk])).content.decode()
    assert "0.14 UNIQ" in page
    assert "Direct 0.11 h + indirect 0.03 h" in page
    assert "€0.13 of this is bought from outside" in page
    assert "From the recipe" in page
    assert "How is this price made?" in page
    assert "provided free by a member" not in page  # no inputs of that kind here


def test_a_draft_offer_is_hidden_from_the_public():
    m, mill, bake = world()
    unit = make_unit("draftunit")
    us.add_first_worker(unit, m)
    item = services.create_item("Cake", "product", "pc")
    draft = services.create_offer(m, unit, item, batch_size=D(2), direct_minutes_per_batch=60)
    from django.test import Client

    assert Client().get(reverse("catalogue:offer", args=[draft.pk])).status_code == 404
    c = Client()
    c.force_login(m.user)
    assert c.get(reverse("catalogue:offer", args=[draft.pk])).status_code == 200


def test_the_lead_time_adds_up():
    m, mill, bake = world()
    # mill cycle 0 days; bakery 1 day + mill 0 + outside inputs 7 days
    assert services.lead_time_days(bake) == 8
    Offer.objects.filter(pk=mill.pk).update(cycle_days=3)
    mill.refresh_from_db()
    assert services.lead_time_days(bake) == 11
    assert services.lead_time_days(mill) == 3


def test_the_item_page_orders_offers_by_name_not_by_price(client):
    m = make_member()
    cake = services.create_item("Cake", "product", "pc")
    prices = {"zeta": D(10), "alpha": D(100), "mid": D(50)}
    for slug, minutes in prices.items():
        unit = make_unit(slug)
        us.add_first_worker(unit, m)
        o = services.create_offer(m, unit, cake, batch_size=D(1), direct_minutes_per_batch=int(minutes))
        services.publish_offer(o, m)
    services.recompute_values()
    page = client.get(reverse("catalogue:item", args=[cake.pk])).content.decode()
    assert page.index("Alpha") < page.index("Mid") < page.index("Zeta")
