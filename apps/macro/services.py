"""Macro numbers other apps read: the planning rate and attractiveness (docs/03 sections 8 and 10)."""

from decimal import Decimal


def planning_rate() -> Decimal:
    """Euros earned per hour of outside sales. For comparing only; UNIQ are never exchanged (HF-4)."""
    from . import world

    return world.planning_rate()


def attractiveness():
    """How many capitalist hours an hour in Unicorn buys, or None while there is not enough data."""
    from . import world

    return world.attractiveness_estimate()
