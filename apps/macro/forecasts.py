"""Forecasts attached to tickets (docs/03 section 11). An expert runs the simulation with the app's live numbers and
attaches a file and five numbers: the four goals, and the share able to live without a job in years 10, 20 and 30."""

from decimal import Decimal, InvalidOperation

from django.utils.translation import gettext as _

from apps.core import audit
from apps.members import services as member_services

from .models import Forecast

GOALS = ("attractive", "growing", "independent", "stable")


class ForecastError(ValueError):
    """A plain-words reason why a forecast cannot be attached."""


def _share(value):
    if value in (None, ""):
        return None
    try:
        share = Decimal(str(value))
    except InvalidOperation:
        raise ForecastError(_("Please enter the shares as numbers between 0 and 1.")) from None
    if not 0 <= share <= 1:
        raise ForecastError(_("Please enter the shares as numbers between 0 and 1."))
    return share


def attach(ticket, author, goals, y10=None, y20=None, y30=None, note="", file=None) -> Forecast:
    if not member_services.is_verified(author):  # HF-13
        raise ForecastError(_("Only verified members can attach a forecast."))
    goals = {g: bool(goals.get(g)) for g in GOALS}
    forecast = Forecast.objects.create(
        ticket=ticket,
        author=author,
        file=file,
        goals=goals,
        can_live_y10=_share(y10),
        can_live_y20=_share(y20),
        can_live_y30=_share(y30),
        note=(note or "")[:2000],
    )
    audit.record(author.number, "forecast.attached", forecast, ticket=ticket.number)
    return forecast
