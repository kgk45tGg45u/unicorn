"""The phase 04 acceptance check: the docs/04 section 7 examples, built through the services and read on the pages."""

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.catalogue import services
from apps.units import services as us
from apps.units.tests.conftest import make_member, make_unit

pytestmark = pytest.mark.django_db
D = Decimal


def unit_for(member, slug, **kw):
    unit = make_unit(slug, **kw)
    us.add_first_worker(unit, member)
    return unit


def test_the_worked_examples_show_on_the_offer_pages(client):
    m = make_member()
    mill_unit, bakery_unit = unit_for(m, "mill"), unit_for(m, "linden-bakery")
    hair_unit = unit_for(m, "hair", kind="service", insurance_confirmed=True)
    wood_unit, oil_unit = unit_for(m, "woodshop"), unit_for(m, "oilpress")

    flour = services.create_item("Flour", "product", "kg")
    mill = services.create_offer(m, mill_unit, flour, batch_size=D(1), direct_minutes_per_batch=3)
    services.publish_offer(mill, m)

    bread_item = services.create_item("Bread", "product", "pc")
    bread = services.create_offer(
        m, bakery_unit, bread_item, batch_size=D(40), cycle_days=1, setup_minutes=30, direct_minutes_per_batch=240
    )
    services.add_input(m, bread, "Flour", "kg", D(24), "unicorn")
    services.add_input(m, bread, "Salt", "kg", D("0.5"), "buy_outside", euro_price_estimate=D("0.6"))
    services.add_input(m, bread, "Yeast", "kg", D("0.4"), "buy_outside", euro_price_estimate=D(5))
    services.add_input(m, bread, "Oven power", "kwh", D(1), "buy_outside", euro_price_estimate=D(3))
    services.add_tool(m, bread, "My oven", "own_free", D(1), D(1000), provided_by=m)
    services.publish_offer(bread, m)

    cut_item = services.create_item("Haircut", "service", "service")
    cut = services.create_offer(
        m, hair_unit, cut_item, duration_minutes=40, capacity=1, travel_minutes=20, place="customer"
    )
    services.add_input(m, cut, "Shampoo", "ml", D(15), "buy_outside", euro_price_estimate=D("0.02"))
    services.add_tool(m, cut, "Scissors", "own_free", D(1), D(1000), provided_by=m)
    services.publish_offer(cut, m)

    oil_item = services.create_item("Finishing oil", "product", "l")
    oil = services.create_offer(m, oil_unit, oil_item, batch_size=D(1), direct_minutes_per_batch=30)
    services.publish_offer(oil, m)
    chair_item = services.create_item("Oak chair", "product", "pc")
    chair = services.create_offer(
        m, wood_unit, chair_item, batch_size=D(4), cycle_days=10, setup_minutes=60, direct_minutes_per_batch=960
    )
    services.add_input(m, chair, "Oak boards", "m3", D("0.16"), "buy_outside", euro_price_estimate=D(900))
    services.add_input(m, chair, "Screws and glue", "pc", D(1), "buy_outside", euro_price_estimate=D(8))
    services.add_input(m, chair, "Finishing oil", "l", D("0.4"), "unicorn")
    services.add_tool(m, chair, "Table saw", "unicorn_owned", D(2), D(2000), euro_price=D(1200))
    services.add_tool(m, chair, "My garage", "own_free", D(1), D(1000), provided_by=m)
    services.publish_offer(chair, m)

    services.recompute_values()

    def page(offer):
        return client.get(reverse("catalogue:offer", args=[offer.pk])).content.decode()

    p = page(bread)
    assert "0.14 UNIQ" in p and "Direct 0.11 h + indirect 0.03 h" in p and "€0.13 of this" in p
    p = page(cut)
    assert "1.00 UNIQ" in p and "Direct 1.00 h + indirect 0.00 h" in p and "€0.30 of this" in p
    p = page(chair)
    assert "4.30 UNIQ" in p and "Direct 4.25 h + indirect 0.05 h" in p and "€38.30 of this" in p

    for name in ("io_offers_csv", "io_inputs_csv", "io_tools_csv"):
        assert client.get(reverse(f"catalogue:{name}")).status_code == 200
