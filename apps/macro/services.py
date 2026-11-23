"""Macro numbers other apps read. Phase 09 fills these in; until then they are stubs."""

from decimal import Decimal

from apps.rules.services import get_param


def planning_rate() -> Decimal:
    """Euros earned per hour of outside sales. For comparing only; UNIQ are never exchanged (HF-4). Stub until P09."""
    return Decimal(str(get_param("economy.planning_rate.fallback_eur_per_hour")))


def attractiveness():
    """How many capitalist hours an hour in Unicorn buys, or None while it is not measured. Stub until P09."""
    return None
