"""Distances and cover areas (docs/06 section 8). Postcode coordinates are looked up when needed."""

import math
from decimal import Decimal

from django.utils.translation import gettext as _

from .models import PostcodePoint

EARTH_RADIUS_KM = 6371


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dphi = p2 - p1
    dlam = math.radians(float(lng2) - float(lng1))
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def clean(postcode) -> str:
    return "".join((postcode or "").split()).upper()


def point_of(country, postcode):
    postcode = clean(postcode)
    if not postcode:
        return None
    return PostcodePoint.objects.filter(country=(country or "DE").upper(), postcode=postcode).first()


def unit_point(unit):
    """The unit's own coordinates, or None when its postcode could not be placed."""
    if unit.lat is None or unit.lng is None:
        return None
    return float(unit.lat), float(unit.lng)


def distance_km(unit, country, postcode):
    """Kilometres between the unit and a postcode, or None when either end cannot be placed."""
    a, b = unit_point(unit), point_of(country, postcode)
    if a is None or b is None:
        return None
    return haversine_km(a[0], a[1], b.lat, b.lng)


def covers(unit, country, postcode) -> bool:
    """True if the postcode is on the unit's list or within its radius; else, without coordinates, the same town."""
    country = (country or "DE").upper()
    if unit.country and unit.country.upper() != country:
        return False
    postcode = clean(postcode)
    if postcode and postcode in {clean(p) for p in (unit.cover_postcodes or [])}:
        return True
    km = distance_km(unit, country, postcode)
    if km is not None:
        return km <= float(unit.cover_radius_km)
    point = point_of(country, postcode)
    return bool(point and unit.town and point.town and point.town.strip().lower() == unit.town.strip().lower())


def within_km(unit_a, unit_b, km) -> bool | None:
    """Whether two units are within `km` of each other; None when either cannot be placed."""
    a, b = unit_point(unit_a), unit_point(unit_b)
    if a is None or b is None:
        return None
    return haversine_km(a[0], a[1], b[0], b[1]) <= float(km)


def area_near(unit, area, country="DE") -> bool | None:
    """Whether any postcode starting with `area` (two digits) lies within the unit's radius; None if unplaceable."""
    centre = unit_point(unit)
    if centre is None or not area:
        return None
    points = PostcodePoint.objects.filter(country=country.upper(), postcode__startswith=area)
    return any(haversine_km(centre[0], centre[1], p.lat, p.lng) <= float(unit.cover_radius_km) for p in points)


def place_unit(unit) -> bool:
    """Set the unit's coordinates from its postcode; leave them empty when the postcode is unknown."""
    point = point_of(unit.country or "DE", unit.postcode)
    if point is None:
        unit.lat = unit.lng = None
        return False
    unit.lat, unit.lng = Decimal(point.lat), Decimal(point.lng)
    return True


def placement_note(unit) -> str:
    if unit.postcode and (unit.lat is None or unit.lng is None):
        return str(_("We could not place this postcode"))
    return ""
