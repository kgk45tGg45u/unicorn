import pytest

from apps.logistics import geo
from apps.units.tests.conftest import make_unit

from .conftest import member_at, place

pytestmark = pytest.mark.django_db


def test_the_distance_between_two_known_points():
    km = geo.haversine_km(52.5200, 13.4050, 48.1351, 11.5820)  # Berlin to Munich
    assert 500 < km < 510
    assert geo.haversine_km(52.52, 13.405, 52.52, 13.405) == 0


def test_inside_and_outside_the_radius():
    unit = place(make_unit("bakery"), "10115", radius=10)
    assert geo.covers(unit, "DE", "10405")  # about 2.8 km away
    assert not geo.covers(unit, "DE", "20095")  # Hamburg, about 255 km
    near = geo.distance_km(unit, "DE", "10405")
    assert 2 < near < 4
    place(unit, "10115", radius=1)
    assert not geo.covers(unit, "DE", "10405")


def test_the_explicit_postcode_list_and_the_country():
    unit = place(make_unit("bakery"), "10115", radius=1)
    unit.cover_postcodes = ["20095"]
    unit.save()
    assert geo.covers(unit, "DE", "200 95")  # listed, spaces ignored
    assert not geo.covers(unit, "AT", "1010")  # never across a border


def test_without_coordinates_the_same_town_counts():
    unit = make_unit("shop", postcode="99999", town="Berlin", country="DE")
    assert geo.covers(unit, "DE", "10405")  # the postcode's place is Berlin
    other = make_unit("far", postcode="99999", town="Hamburg", country="DE")
    assert not geo.covers(other, "DE", "10405")


def test_the_marketplace_marks_offers_deliverable_or_pickup_only(world, client):
    place(world.mill_unit, "20095", town="Hamburg")
    near = member_at("near@x.org", "10405")
    far = member_at("far@x.org", "20095")
    client.force_login(near.user)
    page = client.get("/market/?q=Bread").content.decode()
    assert "Deliverable to you" in page and "Pickup only" not in page
    assert "Pickup only" in client.get("/market/?q=Flour").content.decode()
    client.force_login(far.user)
    assert "Pickup only" in client.get("/market/?q=Bread").content.decode()
    filtered = client.get("/market/?deliverable=1").content.decode()
    assert "Bread" not in filtered and "Flour" in filtered


def test_a_member_three_kilometres_away_sees_deliverable(world, client):
    member = member_at("near@x.org", "10405")
    client.force_login(member.user)
    assert "Deliverable to you" in client.get("/market/?q=Bread&deliverable=1").content.decode()
