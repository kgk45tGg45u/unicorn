"""How the units app and the outside shop meet: a council decision of kind `outside_prices` sets what is sold."""

from apps.catalogue.models import Offer
from apps.members.models import Member
from apps.units import services as unit_services

from . import services


def _apply(decision):
    p = decision.payload
    services.apply_outside_offer(
        Offer.objects.get(pk=p["offer"]), p["price"], p["currency"], Member.objects.get(number=p["seller"])
    )


def register():
    unit_services.DECISION_ACTIONS["outside_prices"] = _apply
