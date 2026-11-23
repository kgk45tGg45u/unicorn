from decimal import Decimal

import pytest

from apps.logistics import services
from apps.logistics.models import PostcodePoint

from .conftest import make_carrier, make_courier

pytestmark = pytest.mark.django_db


def test_a_destination_abroad_shows_only_carriers_for_that_country(world):
    make_carrier(name="DHL parcel", countries=("DE", "AT"))
    make_carrier(name="Poste", countries=("IT",), base="9")
    assert [c.name for c in services.carriers_for("AT")] == ["DHL parcel"]
    assert [c.name for c in services.carriers_for("it")] == ["Poste"]
    assert services.carriers_for("FR") == []
    p = services.propose(world.bakery_unit, "AT", "1010")
    assert p.mode == "capitalist_carrier" and p.carrier.name == "DHL parcel"
    with pytest.raises(services.LogisticsError, match="cannot bring"):
        services.propose(world.bakery_unit, "FR", "75001")


def test_outside_the_eu_the_notice_appears():
    notice = services.abroad_notice("DE", "CH")
    assert "Customs declaration needed" in notice and "tax adviser" in notice
    assert services.abroad_notice("DE", "AT") == "" and services.abroad_notice("DE", "DE") == ""


def test_a_proposal_for_a_non_eu_country_carries_the_notice(world):
    make_carrier(name="Swiss post", countries=("CH",), base="20")
    PostcodePoint.objects.create(
        country="CH", postcode="8001", town="Zurich", lat=Decimal("47.37"), lng=Decimal("8.54")
    )
    assert "Customs" in services.propose(world.bakery_unit, "CH", "8001").notice


def test_couriers_never_deliver_across_a_border(world):
    courier, unit, offer, co = make_courier(world, radius=2000)
    make_carrier(name="DHL parcel", countries=("DE", "AT"))
    unit.country = "DE"
    unit.save()
    p = services.propose(world.bakery_unit, "AT", "1010")
    assert p.mode == "capitalist_carrier"
