"""The plan check (docs/06 section 2). It returns green, amber or red with one plain sentence per point.

It never rejects on its own and never changes data (HF-15): people decide what a red point means.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.utils import timezone
from django.utils.translation import gettext as _

from apps.rules.services import get_param


@dataclass
class CheckPoint:
    color: str  # "green" | "amber" | "red"
    text: str


@dataclass
class CheckResult:
    points: list[CheckPoint]

    @property
    def color(self):
        return (
            "red"
            if any(p.color == "red" for p in self.points)
            else "amber"
            if any(p.color == "amber" for p in self.points)
            else "green"
        )


def _pk(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dec(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except InvalidOperation:
        return Decimal(0)


def _what(request):
    """The item, the trade and the unit the request is about."""
    from apps.catalogue.models import Item, Offer
    from apps.units.models import Unit

    item = unit = None
    trade = request.get("trade_code") or ""
    if request.get("offer"):
        offer = Offer.objects.select_related("item", "unit").filter(pk=_pk(request["offer"])).first()
        if offer:
            item, unit = offer.item, offer.unit
    if item is None and request.get("item"):
        item = Item.objects.filter(pk=_pk(request["item"])).first()
    if unit is None and request.get("unit"):
        unit = Unit.objects.filter(pk=_pk(request["unit"])).first()
    trade = trade or (item.trade_code if item else "") or (unit.trade_code if unit else "")
    return item, trade, unit


def _closure(variant, item, trade, unit):
    from django.db.models import Q

    q = Q()
    if item is not None:
        q |= Q(item=item)
    if trade:
        q |= Q(trade_code=trade)
    if unit is not None:
        q |= Q(unit=unit)
    if not q:
        return None
    return variant.closures.filter(q).filter(Q(closed_at__isnull=True) | Q(closed_at__gt=timezone.now())).first()


def _euros_wanted(request) -> Decimal:
    once = _dec(request.get("eur_once") or request.get("amount_eur"))
    monthly = _dec(request.get("eur_monthly") or request.get("euros_per_batch"))
    return once + 12 * monthly


def _budget_line(variant, trade, request):
    lines = variant.budget_lines
    if trade and lines.filter(trade_code=trade, eur__gt=0).exists():
        return lines.filter(trade_code=trade, eur__gt=0).first()
    category = "tools" if request.get("type") in ("purchase", "plan_proposal") else "materials"
    return lines.filter(category=category, trade_code="").first()


def _spent_this_year(variant, line, request) -> Decimal:
    """Euros of purchase requests already asked for within the line's trade (or category) in the plan's period."""
    from apps.tradefund import purchases
    from apps.tradefund.models import PurchaseRequest

    period = variant.period
    rows = PurchaseRequest.objects.filter(created_at__date__gte=period.starts_on, created_at__date__lte=period.ends_on)
    rows = rows.exclude(status="rejected").exclude(pk=request.get("purchase"))
    if line.trade_code:
        rows = rows.filter(item__trade_code=line.trade_code)
    return sum((purchases.est_eur(r) for r in rows), Decimal(0))


def _euro_point(variant, request, trade):
    from apps.tradefund import allocation

    wanted = _euros_wanted(request)
    if wanted <= 0:
        return CheckPoint("green", _("This needs no euros from the trade fund."))
    if not variant.budget_lines.filter(eur__gt=0).exists():
        return CheckPoint("green", _("The plan sets no euro budget yet, so nothing is over it."))
    line = _budget_line(variant, trade, request)
    left = (line.eur - _spent_this_year(variant, line, request)) if line else Decimal(0)
    months = allocation.reserve_months()
    red_reserve = months is not None and months < Decimal(str(get_param("alarms.euro_reserve_red_months")))
    amber_reserve = months is not None and months < Decimal(str(get_param("alarms.euro_reserve_amber_months")))
    if wanted > left:
        return CheckPoint(
            "red",
            _("This needs about %(wanted)s euros over a year, and %(left)s are left in this part of the plan's budget.")
            % {"wanted": wanted.quantize(Decimal("1")), "left": max(left, Decimal(0)).quantize(Decimal("1"))},
        )
    if red_reserve:
        return CheckPoint("red", _("It fits the budget, but the euro reserve of the trade fund is low (red)."))
    if amber_reserve:
        return CheckPoint("amber", _("It fits the budget, but the euro reserve of the trade fund is getting low."))
    return CheckPoint(
        "green", _("It fits the plan's budget (about %(wanted)s euros).") % {"wanted": wanted.quantize(Decimal("1"))}
    )


def _scarce_points(request, item):
    from apps.catalogue.models import Offer
    from apps.macro import lights

    points = []
    if not request.get("offer"):
        return points
    offer = Offer.objects.filter(pk=_pk(request["offer"])).first()
    if offer is None:
        return points
    for inp in offer.inputs.filter(source="unicorn").select_related("item"):
        if lights.item_red(inp.item):
            points.append(
                CheckPoint("amber", _("%(item)s is short at the moment, and this needs it.") % {"item": inp.item.name})
            )
    return points


def _demand_point(request, item, unit):
    from datetime import timedelta

    from apps.market.models import SearchMiss, WaitingListEntry

    if request.get("kind") not in ("service", "social") and (item is None or item.kind != "service"):
        return None
    start = timezone.localdate().replace(day=1) - timedelta(days=62)
    name = (item.name if item else request.get("name", "")).lower()
    from apps.logistics import geo

    misses = SearchMiss.objects.filter(text__icontains=name, month__gte=start) if name else SearchMiss.objects.none()
    if unit is not None and unit.lat is not None:  # demand within the unit's cover area, in kilometres
        near = [m for m in misses if geo.area_near(unit, m.area, unit.country or "DE")]
        searched = bool(near)
    else:
        searched = misses.exists()
    seen = bool(name) and (
        searched
        or (item is not None and WaitingListEntry.objects.filter(item=item, fulfilled_at__isnull=True).exists())
    )
    if seen:
        return CheckPoint("green", _("Members have searched for or asked for this nearby."))
    return CheckPoint("amber", _("No visible demand yet; it may still be worth trying."))


def check(request: dict) -> CheckResult:
    """Never raises for the caller's data and never changes anything (HF-15)."""
    from apps.plan import services

    variant = services.running_variant()
    if variant is None:
        return CheckResult([CheckPoint("green", _("There is no yearly plan yet, so nothing in it is against this."))])
    item, trade, unit = _what(request)
    points = []
    closure = _closure(variant, item, trade, unit)
    if closure is not None:
        points.append(
            CheckPoint(
                "red", _("The yearly plan closes this trade or item from %(date)s.") % {"date": closure.from_date}
            )
        )
    else:
        points.append(CheckPoint("green", _("It is not on the plan's closure list.")))
    points.append(_euro_point(variant, request, trade))
    points.extend(_scarce_points(request, item))
    demand = _demand_point(request, item, unit)
    if demand is not None:
        points.append(demand)
    focus = variant.focus_items.filter(item=item) if item is not None else variant.focus_items.none()
    if (item is not None and focus.exists()) or (trade and variant.focus_items.filter(trade_code=trade).exists()):
        points.append(CheckPoint("green", _("This is a focus of the plan.")))
    return CheckResult(points)
