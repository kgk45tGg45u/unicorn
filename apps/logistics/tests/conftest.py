"""Builders for the logistics tests: the fixture postcodes, a bakery in Berlin and a buyer."""

import pathlib
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from apps.logistics.management.commands.load_postcodes import load
from apps.market.tests.conftest import World, fund

D = Decimal
IBAN = "DE89 3704 0044 0532 0130 00"
FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "DE_sample.txt"


@pytest.fixture(autouse=True)
def defaults_loaded(db):
    call_command("load_defaults", stdout=StringIO())
    call_command("loaddata", "contracts", verbosity=0)
    load(FIXTURE, "DE")


def place(unit, postcode, town="Berlin", radius=10):
    unit.postcode, unit.town, unit.country, unit.cover_radius_km = postcode, town, "DE", radius
    unit.save()
    unit.refresh_from_db()
    return unit


@pytest.fixture
def world():
    w = World()
    place(w.bakery_unit, "10115")
    return w


def member_at(email, postcode, uniq=20):
    from apps.units.tests.conftest import make_member

    m = make_member(email, "Buyer")
    m.postcode, m.country = postcode, "DE"
    m.save()
    fund(m, uniq)
    return m


def make_courier(world, postcode="10115", radius=15, speed=None, tool_value="10", lifetime=1000):
    """A courier unit with a "Delivery" service offer, a bicycle that Unicorn owns, and its CourierOffer."""
    from apps.catalogue import models as cm
    from apps.catalogue import services as cat
    from apps.logistics.models import CourierOffer
    from apps.market.tests.conftest import unit_for
    from apps.units.tests.conftest import make_member

    courier = make_member("courier@x.org", "Courier")
    unit = unit_for(courier, "couriers", kind="courier", insurance_confirmed=True)
    place(unit, postcode, radius=radius)
    item = cat.create_item("Delivery", "service", "service")
    offer = cat.create_offer(courier, unit, item, duration_minutes=15, capacity=1)
    tool = cat.add_tool(courier, offer, "Bicycle", "unicorn_owned", 1, lifetime)
    cm.OfferTool.objects.filter(pk=tool.pk).update(value_uniq=D(tool_value))
    cat.publish_offer(offer, courier)
    co = CourierOffer.objects.create(offer=offer, speed_kmh=speed)
    return courier, unit, offer, co


def make_carrier(base="5.49", countries=("DE",), per_kg="0", max_kg="31.5", name="DHL parcel"):
    from apps.logistics.models import Carrier

    return Carrier.objects.create(
        name=name,
        countries=list(countries),
        rate_rules={"base_eur": float(base), "per_kg_eur": float(per_kg), "max_kg": float(max_kg)},
    )


def ready_line(world, member, quantity=2, delivery=None):
    """Order bread and make it: the line is ready to be handed over or sent."""
    from apps.market import services as market

    line = market.place_order(member, world.bread, D(quantity), delivery=delivery)
    po = line.production_order
    market.start_production(po, world.baker)
    market.complete_production(po, world.baker, quantity)
    line.refresh_from_db()
    return line
