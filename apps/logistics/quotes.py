"""What a delivery costs (docs/06 section 8). A courier's quote is a labour value (HF-3); a carrier's is euros."""

from decimal import Decimal

from apps.core.money import cur, uniq
from apps.rules.services import get_param
from apps.tradefund import fx

from .geo import haversine_km

D = Decimal


def courier_minutes(courier_offer, distance_km) -> Decimal:
    """Minutes of the trip: distance over speed, plus the minutes of the stop."""
    speed = courier_offer.speed_kmh or D(str(get_param("logistics.courier_speed_kmh")))
    stop = (
        courier_offer.stop_minutes
        if courier_offer.stop_minutes is not None
        else D(str(get_param("logistics.stop_minutes")))
    )
    return D(str(distance_km)) / D(str(speed)) * 60 + D(str(stop))


def courier_quote(courier_offer, from_point, to_point, distance_km=None) -> tuple[Decimal, Decimal]:
    """(UNIQ, euros) of one delivery: its hours plus the wear of the tools, and the euros of its inputs.

    This is the delivery's labour value, computed by the rules of every service. Nobody sets it by hand (HF-3).
    """
    from apps.macro.accounts import depreciation_per_unit

    km = (
        haversine_km(from_point.lat, from_point.lng, to_point.lat, to_point.lng) if distance_km is None else distance_km
    )
    hours = courier_minutes(courier_offer, km) / 60
    labour = uniq(hours + depreciation_per_unit(courier_offer.offer))
    euros = D(0)
    for row in courier_offer.offer.inputs.filter(source="buy_outside"):
        euros += fx.to_eur((row.euro_price_estimate or D(0)) * row.quantity_per_batch, row.currency)
    return labour, cur(euros)


def carrier_quote(carrier, weight_kg=0) -> Decimal | None:
    """The carrier's euros for a parcel, or None when the parcel is too heavy for it."""
    rules = carrier.rate_rules or {}
    weight = D(str(weight_kg or 0))
    if weight > D(str(rules.get("max_kg", 1000))):
        return None
    eur = D(str(rules.get("base_eur", 0))) + D(str(rules.get("per_kg_eur", 0))) * weight
    return cur(fx.to_eur(eur, carrier.currency))
