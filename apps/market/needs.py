"""The needs board and its signals (docs/06 section 7, docs/03 section 9).

Everything here informs. Nothing assigns work, creates an order or an obligation (HF-10, HF-15).
"""

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.db.models import F, Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.catalogue import services as catalogue
from apps.core import audit
from apps.core.money import cur
from apps.units import services as unit_services

from .models import (
    Booking,
    DemandSignal,
    OrderLine,
    ProductionOrder,
    PurchaseNeed,
    Sale,
    SearchMiss,
    ServiceSlot,
    StockLot,
    WaitingListEntry,
)
from .services import BERLIN, MarketError, can_buy, today

DELIVERABLE_DAYS = 30
RATIO_HIGH = Decimal("1.1")
RATIO_LOW = Decimal("0.9")
MAX_RATIO = Decimal("99.9999")


# --- Waiting lists ---


def _active_offers(item):
    return catalogue.Offer.objects.filter(item=item, status="active", unit__status__in=["trial", "open"])


def deliverable(item) -> bool:
    """True if some active offer of the item can deliver within 30 days."""
    return any(catalogue.lead_time_days(o) <= DELIVERABLE_DAYS for o in _active_offers(item).select_related("item"))


def join_waiting_list(member, item, quantity=1) -> WaitingListEntry:
    try:
        quantity = Decimal(str(quantity))
    except (InvalidOperation, ValueError, TypeError):
        raise MarketError(_("Please enter how many you want.")) from None
    if quantity <= 0:
        raise MarketError(_("Please enter how many you want."))
    if not can_buy(member):
        raise MarketError(_("Only members can join a waiting list. Please finish joining first."))
    if item.status == "retired":
        raise MarketError(_("Nobody will make this any more."))
    if deliverable(item):
        raise MarketError(_("You can order this now."))
    entry = WaitingListEntry.objects.filter(member=member, item=item, fulfilled_at__isnull=True).first()
    if entry is None:
        entry = WaitingListEntry.objects.create(member=member, item=item, quantity=quantity)
    else:
        entry.quantity = quantity
        entry.save(update_fields=["quantity"])
    audit.record(member.number, "waiting_list.joined", entry)
    return entry


def leave_waiting_list(member, item):
    return WaitingListEntry.objects.filter(member=member, item=item, fulfilled_at__isnull=True).delete()


# --- Searches that found nothing ---


def area_of(member) -> str:
    digits = "".join(c for c in (getattr(member, "postcode", "") or "") if c.isdigit())
    return digits[:2] if len(digits) >= 2 else ""


def record_search_miss(member, text):
    """Count a search with no result by area and text. The searcher is not stored."""
    text = " ".join((text or "").lower().split())[:120]
    area = area_of(member) if member is not None else ""
    if not text or not area:
        return None
    month = today().replace(day=1)
    row, created = SearchMiss.objects.get_or_create(area=area, text=text, month=month)
    if not created:
        SearchMiss.objects.filter(pk=row.pk).update(count=F("count") + 1)
    return row


# --- Demand and supply, month by month ---


def _month_range(month: date):
    first = month.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    return (
        datetime(first.year, first.month, 1, tzinfo=BERLIN),
        datetime(nxt.year, nxt.month, 1, tzinfo=BERLIN),
    )


def _previous_month(day):
    return (day.replace(day=1) - timedelta(days=1)).replace(day=1)


def demand_and_supply(offer, month: date):
    """Demand: ordered (or booked) plus waiting. Supply: made ahead plus made (sessions: seats offered)."""
    a, b = _month_range(month)
    waiting_total = WaitingListEntry.objects.filter(
        item=offer.item, created_at__lt=b, fulfilled_at__isnull=True
    ).aggregate(t=Sum("quantity"))["t"] or Decimal("0")
    sharing = max(1, _active_offers(offer.item).count())
    waiting = waiting_total / sharing
    if offer.is_service:
        booked = (
            Booking.objects.filter(slot__offer=offer, created_at__gte=a, created_at__lt=b)
            .exclude(status="cancelled")
            .count()
        )
        slots = ServiceSlot.objects.filter(offer=offer, starts_at__gte=a, starts_at__lt=b).exclude(status="cancelled")
        return Decimal(booked) + waiting, Decimal(slots.count() * (offer.capacity or 1))
    ordered = OrderLine.objects.filter(offer=offer, created_at__gte=a, created_at__lt=b).exclude(
        status="cancelled"
    ).aggregate(t=Sum("quantity"))["t"] or Decimal("0")
    sold = Sale.objects.filter(offer=offer, status="paid", paid_at__gte=a, paid_at__lt=b).aggregate(t=Sum("quantity"))[
        "t"
    ] or Decimal("0")
    made = ProductionOrder.objects.filter(offer=offer, status="done", done_at__gte=a, done_at__lt=b).aggregate(
        t=Sum("quantity_done")
    )["t"] or Decimal("0")
    shelf = StockLot.objects.filter(offer=offer, status="available", made_at__lt=a).aggregate(t=Sum("quantity_left"))[
        "t"
    ] or Decimal("0")
    return ordered + sold + waiting, made + shelf


def _council_notify(unit, subject, body):
    for w in unit_services.council_members(unit):
        unit_services._notify(w.member, subject, body)


def run_demand_signals(month: date | None = None):
    """Compute the signal of every active offer for a month (default: the last full month). Safe to run twice.

    Above 1.1 for two months in a row, the unit's council is told that members want more, and the item is
    marked "wanted". Below 0.9 for two months, it is told to consider making less ahead. Only suggestions (HF-15).
    """
    month = (month or _previous_month(today())).replace(day=1)
    before = _previous_month(month)
    count = 0
    offers = catalogue.Offer.objects.filter(status="active").select_related("item", "unit")
    for offer in offers:
        demand, supply = demand_and_supply(offer, month)
        if supply > 0:
            ratio = min(demand / supply, MAX_RATIO)
        elif demand > 0:
            ratio = MAX_RATIO
        else:
            continue
        earlier = DemandSignal.objects.filter(offer=offer, month=before).first()
        flag = ""
        if ratio > RATIO_HIGH and earlier is not None and earlier.ratio > RATIO_HIGH:
            flag = "wanted"
        elif ratio < RATIO_LOW and earlier is not None and earlier.ratio < RATIO_LOW:
            flag = "less"
        row, created = DemandSignal.objects.update_or_create(
            offer=offer,
            month=month,
            defaults={"demand": demand, "supply": supply, "ratio": ratio.quantize(Decimal("0.0001")), "flag": flag},
        )
        count += 1
        if created and flag:
            audit.record("system", f"demand.{flag}", offer, month=f"{month:%Y-%m}", ratio=str(row.ratio))
            if flag == "wanted":
                _council_notify(
                    offer.unit,
                    _("Members want more %(item)s") % {"item": offer.item.name},
                    _("Members want more than you make: consider a larger batch or weekly plan.")
                    + " "
                    + _("(%(item)s: %(demand)s wanted, %(supply)s made.)")
                    % {"item": offer.item.name, "demand": demand.normalize(), "supply": supply.normalize()},
                )
            else:
                _council_notify(
                    offer.unit,
                    _("Consider making less %(item)s ahead") % {"item": offer.item.name},
                    _("Consider making less ahead: members ordered less than you made two months in a row."),
                )
    return count


# --- The needs board ---


def _average_value(item):
    values = [o.value_total for o in _active_offers(item) if o.value_total > 0]
    return (sum(values, Decimal("0")) / len(values)) if values else None


def _hours_a_month(item, quantity):
    average = _average_value(item)
    return cur(quantity * average) if average is not None else None


def _wanted_cards():
    cards = {}
    waiting = WaitingListEntry.objects.filter(fulfilled_at__isnull=True).select_related("item")
    for entry in waiting:
        c = cards.setdefault(entry.item_id, {"item": entry.item, "people": set(), "quantity": Decimal("0")})
        c["people"].add(entry.member_id)
        c["quantity"] += entry.quantity
    latest = DemandSignal.objects.order_by("-month").values_list("month", flat=True).first()
    if latest is not None:
        for sig in DemandSignal.objects.filter(month=latest, flag="wanted").select_related("offer__item"):
            c = cards.setdefault(sig.offer.item_id, {"item": sig.offer.item, "people": set(), "quantity": Decimal("0")})
            c["quantity"] = max(c["quantity"], sig.demand - sig.supply)
            c["marked"] = True
    out = []
    for c in cards.values():
        out.append(
            {
                "item": c["item"],
                "people": len(c["people"]),
                "quantity": c["quantity"],
                "marked": c.get("marked", False),
                "hours": _hours_a_month(c["item"], c["quantity"]),
                "makers": list(_active_offers(c["item"]).select_related("unit")[:3]),
            }
        )
    return sorted(out, key=lambda c: c["item"].name.lower())


def _outside_cards():
    start = today().replace(day=1)
    for _i in range(2):
        start = _previous_month(start)
    rows = PurchaseNeed.objects.filter(month__gte=start).select_related("item", "unit")
    cards = {}
    for need in rows:
        c = cards.setdefault(
            need.item_id, {"item": need.item, "euros": Decimal("0"), "units": set(), "currency": need.currency}
        )
        c["euros"] += need.euro_estimate
        c["units"].add(need.unit_id)
    out = []
    for c in cards.values():
        out.append(
            {
                "item": c["item"],
                "euros_per_month": cur(c["euros"] / 3),
                "currency": c["currency"],
                "units": len(c["units"]),
                "placeholder": c["item"].status == "placeholder",
                "makers": list(_active_offers(c["item"]).select_related("unit")[:3]),
            }
        )
    return sorted(out, key=lambda c: (-c["euros_per_month"], c["item"].name.lower()))


def _missing_near(member):
    area = area_of(member) if member is not None else ""
    if not area:
        return []
    start = today().replace(day=1)
    for _i in range(2):
        start = _previous_month(start)
    rows = (
        SearchMiss.objects.filter(area=area, month__gte=start)
        .values("text")
        .annotate(total=Sum("count"))
        .order_by("-total", "text")[:10]
    )
    return [{"text": r["text"], "count": r["total"]} for r in rows]


def needs_board(member=None):
    """The four sections of docs/06 section 7, and the needs that match the member's skills."""
    wanted, outside = _wanted_cards(), _outside_cards()
    codes = set()
    if member is not None:
        codes = {c for c in member.skills.values_list("trade_code", flat=True) if c}
    matching = [c for c in wanted + outside if c["item"].trade_code and c["item"].trade_code in codes]
    from apps.plan import apply as plan_apply

    return {
        "wanted": wanted,
        "outside": outside,
        "missing": _missing_near(member),
        "matching": matching,
        "focus": plan_apply.focus_items(),
    }


def my_units(member):
    """Units the member works in, where "I can make this" can add an offer."""
    if member is None:
        return []
    return [
        w.unit
        for w in member.unit_memberships.filter(left_at__isnull=True).select_related("unit")
        if w.unit.kind != "coordination" and w.unit.status in ("trial", "open")
    ]


# --- When an offer is published ---


def on_offer_published(offer, member):
    """Tell the waiting members; thank the maker if the item was wanted or bought from outside (docs/06 section 7)."""
    from apps.core.hooks import RECOGNITION_HOOK

    item = offer.item
    recent = today().replace(day=1)
    for _i in range(2):
        recent = _previous_month(recent)
    latest = DemandSignal.objects.order_by("-month").values_list("month", flat=True).first()
    was_wanted = (
        item.status == "placeholder"
        or WaitingListEntry.objects.filter(item=item, fulfilled_at__isnull=True).exists()
        or PurchaseNeed.objects.filter(item=item, month__gte=recent).exists()
        or (latest is not None and DemandSignal.objects.filter(offer__item=item, month=latest, flag="wanted").exists())
    )
    if catalogue.lead_time_days(offer) <= DELIVERABLE_DAYS:
        now = timezone.now()
        for entry in WaitingListEntry.objects.filter(item=item, fulfilled_at__isnull=True).select_related(
            "member__user"
        ):
            entry.fulfilled_at = now
            entry.save(update_fields=["fulfilled_at"])
            unit_services._notify(
                entry.member,
                _("%(item)s is available now") % {"item": item.name},
                _("%(unit)s now makes %(item)s. You can order it in the market.")
                % {"unit": offer.unit.name, "item": item.name},
            )
    if was_wanted:
        audit.record(member.number, "need.filled", item, offer=offer.pk)
        RECOGNITION_HOOK(member, "filled_need", item)


def register():
    if on_offer_published not in catalogue.PUBLISH_HOOKS:
        catalogue.PUBLISH_HOOKS.append(on_offer_published)
