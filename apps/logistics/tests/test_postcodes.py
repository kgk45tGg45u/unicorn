from decimal import Decimal

import pytest

from apps.logistics import geo
from apps.logistics.management.commands.load_postcodes import load
from apps.logistics.models import PostcodePoint
from apps.logistics.tests.conftest import FIXTURE
from apps.units.tests.conftest import make_unit

pytestmark = pytest.mark.django_db


def test_the_fixture_loads_and_duplicates_are_averaged():
    assert PostcodePoint.objects.filter(country="DE").count() == 5  # the Austrian line is skipped
    mitte = PostcodePoint.objects.get(country="DE", postcode="10115")
    assert mitte.town == "Berlin"  # the first place name is kept
    assert mitte.lat == Decimal("52.532500") and mitte.lng == Decimal("13.385000")  # the average of two places
    assert load(FIXTURE, "AT") == 1 and PostcodePoint.objects.filter(country="AT").exists()


def test_a_unit_gets_coordinates_from_its_postcode():
    unit = make_unit("shop", postcode="10115", town="Berlin", country="DE")
    unit.refresh_from_db()
    assert unit.lat == Decimal("52.532500") and unit.lng == Decimal("13.385000")
    unit.postcode = "80331"
    unit.save()
    unit.refresh_from_db()
    assert unit.lat == Decimal("48.137200")


def test_an_unknown_postcode_leaves_the_coordinates_empty_and_says_so():
    unit = make_unit("shop", postcode="99999", town="Nowhere", country="DE")
    unit.refresh_from_db()
    assert unit.lat is None and unit.lng is None
    assert geo.placement_note(unit) == "We could not place this postcode"
    assert geo.placement_note(make_unit("other", postcode="10115", country="DE")) == ""
