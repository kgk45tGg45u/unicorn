"""Euro priorities, the reserve, and pausing euro-hungry offers (docs/07 section 10).

Each month the euros held are used in this order, each step only with what is left (the simulation's "tools first"):
already approved payments, tool purchases, materials, guarantee claims and benefits, the reserve, then extras.
With `economy.euro_priority = goods`, materials come before tools.
"""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.money import cur
from apps.core.notify import notify
from apps.rules.services import get_param

from . import books, fx
from .models import FundEntry, Holder, PaymentRequest, PurchaseRequest

PAUSED_NOTE = _("Paused: the trade fund is short of euros")


def _months_so_far(first_date, today, cap=12) -> int:
    months = (today.year - first_date.year) * 12 + today.month - first_date.month + 1
    return max(1, min(cap, months))


def _eur(qs_rows) -> Decimal:
    return cur(sum((fx.to_eur(a, c) for c, a in qs_rows), Decimal(0)))


def outgoings_last_12_months(today=None, kinds=("payment_out",), exclude_reason=()):
    """Confirmed payments out in the last 12 months, in euros, and the months they cover."""
    today = today or timezone.localdate()
    start = timezone.now() - timedelta(days=365)
    qs = FundEntry.objects.filter(kind__in=kinds, created_at__gte=start).exclude(reason_kind__in=exclude_reason)
    rows = qs.values_list("currency").annotate(t=Sum("amount"))
    total = -_eur((c, t) for c, t in rows)
    first = FundEntry.objects.order_by("seq").values_list("created_at", flat=True).first()
    months = _months_so_far(timezone.localtime(first).date(), today) if first else 1
    return total, months


def monthly_outgoings_eur(today=None) -> Decimal:
    """The average of the last 12 months of confirmed payments out (or of the months so far)."""
    total, months = outgoings_last_12_months(today)
    return cur(total / months)


def free_holdings_eur() -> Decimal:
    return cur(sum((fx.to_eur(books.free(h), h.currency) for h in Holder.objects.exclude(status="left")), Decimal(0)))


def reserve_months(today=None):
    """Free holdings in euros divided by the monthly outgoings; None while nothing has been paid out yet."""
    outgoing = monthly_outgoings_eur(today)
    if outgoing <= 0:
        return None
    return (free_holdings_eur() / outgoing).quantize(Decimal("0.01"))


def committed_eur() -> Decimal:
    rows = (
        PaymentRequest.objects.filter(status__in=PaymentRequest.OPEN).values_list("currency").annotate(t=Sum("amount"))
    )
    return _eur((c, t) for c, t in rows)


def available_eur() -> Decimal:
    return free_holdings_eur() - committed_eur()


# --- The monthly allocation ---


def _ratio(offer) -> Decimal:
    return (offer.euro_content / offer.value_total) if offer.value_total else Decimal(0)


def _usual(offer, since) -> Decimal:
    """Members' usual purchases of this offer, in UNIQ of orders over the last 3 months."""
    from apps.market.models import OrderLine

    total = (
        OrderLine.objects.filter(offer=offer, created_at__gte=since)
        .exclude(status="cancelled")
        .aggregate(t=Sum("total_uniq"))["t"]
    )
    return total or Decimal(0)


def _notify_unit(unit, text):
    from apps.units import services as unit_services

    for w in unit_services.workers(unit).select_related("member"):
        notify(w.member, text, f"/units/{unit.slug}/")


def _fund_waiting(requests, left):
    """Start the payment of waiting purchases that fit into what is left."""
    from . import purchases

    for pr in requests:
        need = purchases.est_eur(pr)
        if need <= left:
            purchases.start_payment(pr)
            pr.refresh_from_db()
            if pr.status != "waiting_for_euros":
                left -= need
    return left


def _materials(left, now):
    """Fund the materials; if they do not fit, pause the most euro-hungry offers; unpause when euros allow."""
    from apps.catalogue.models import Offer

    from . import purchases

    waiting = list(PurchaseRequest.objects.filter(status="waiting_for_euros", source="recipe_input").order_by("id"))
    paused = list(Offer.objects.filter(paused_for_euros=True).select_related("unit"))
    paused_units = {o.unit_id for o in paused}
    ratio_of_unit = {}
    for o in paused:
        ratio_of_unit[o.unit_id] = max(ratio_of_unit.get(o.unit_id, Decimal(0)), _ratio(o))
    first = [r for r in waiting if r.unit_id not in paused_units]
    later = sorted([r for r in waiting if r.unit_id in paused_units], key=lambda r: ratio_of_unit[r.unit_id])
    left = _fund_waiting(first + later, left)

    # Unpause (in reverse order of pausing: the least euro-hungry first) when the unit's materials are funded.
    still_waiting_units = set(
        PurchaseRequest.objects.filter(status="waiting_for_euros", source="recipe_input").values_list(
            "unit_id", flat=True
        )
    )
    unpaused = 0
    for o in sorted(paused, key=_ratio):
        if o.unit_id not in still_waiting_units:
            o.paused_for_euros, o.status, o.status_note = False, "active", ""
            o.save(update_fields=["paused_for_euros", "status", "status_note"])
            _notify_unit(
                o.unit, _("%(offer)s is open again: the trade fund has euros for its materials.") % {"offer": o}
            )
            audit.record("system", "offer.unpaused_for_euros", o)
            unpaused += 1

    # Pause: what still waits, and belongs to units that are not paused, is the shortfall.
    still = [
        r
        for r in PurchaseRequest.objects.filter(status="waiting_for_euros", source="recipe_input")
        if r.unit_id not in paused_units
    ]
    shortfall = sum((purchases.est_eur(r) for r in still), Decimal(0))
    pause_count = 0
    if shortfall > 0:
        need_of_unit = {}
        for r in still:
            need_of_unit[r.unit_id] = need_of_unit.get(r.unit_id, Decimal(0)) + purchases.est_eur(r)
        candidates = [
            o
            for o in Offer.objects.filter(status="active", unit_id__in=need_of_unit, euro_content__gt=0).select_related(
                "unit"
            )
            if o.value_total > 0
        ]
        candidates.sort(key=lambda o: (-_ratio(o), o.pk))
        since = now - timedelta(days=90)
        all_active = list(Offer.objects.filter(status="active")) + list(Offer.objects.filter(paused_for_euros=True))
        usual = {o.pk: _usual(o, since) for o in all_active}
        total_usual = sum(usual.values(), Decimal(0))
        if total_usual > 0:
            weight, limit = (
                (lambda o: usual[o.pk]),
                (1 - Decimal(str(get_param("economy.min_offer_share_when_euros_short")))) * total_usual,
            )
        else:  # no orders yet: count offers instead
            weight = lambda o: Decimal(1)  # noqa: E731
            limit = (1 - Decimal(str(get_param("economy.min_offer_share_when_euros_short")))) * len(all_active)
        paused_weight = sum((weight(o) for o in all_active if o.paused_for_euros), Decimal(0))
        relieved = set()
        for o in candidates:
            if shortfall <= 0:
                break
            if paused_weight + weight(o) > limit:
                continue  # at least 44% of usual purchases stay on offer
            o.paused_for_euros, o.status, o.status_note = True, "paused", str(PAUSED_NOTE)
            o.save(update_fields=["paused_for_euros", "status", "status_note"])
            paused_weight += weight(o)
            if o.unit_id not in relieved:
                shortfall -= need_of_unit[o.unit_id]
                relieved.add(o.unit_id)
            _notify_unit(
                o.unit, _("%(offer)s is paused: the trade fund is short of euros for materials.") % {"offer": o}
            )
            audit.record("system", "offer.paused_for_euros", o)
            pause_count += 1
    return left, {"paused": pause_count, "unpaused": unpaused}


def allocate(now=None) -> dict:
    """Run the monthly order of priorities. Safe to run twice: it only acts on what still waits."""
    from . import benefits

    now = now or timezone.now()
    left = available_eur()  # 1. payments already approved are already counted as committed
    result = {"paused": 0, "unpaused": 0}

    def tools(left):
        return _fund_waiting(
            PurchaseRequest.objects.filter(status="waiting_for_euros", source="tool").order_by("id"), left
        )

    def materials(left):
        left, info = _materials(left, now)
        result.update(info)
        return left

    steps = [tools, materials] if get_param("economy.euro_priority") == "tools" else [materials, tools]
    for step in steps:  # 2. and 3.
        left = step(left)
    benefits.run_monthly(now=now)  # 4. guarantee claims, then benefits, within the month's budget
    result["reserve_months"] = reserve_months()  # 5. the reserve is what is left: it feeds the euro-reserve light
    # 6. extras (tools and land from the plan's lists, only above a full reserve) come with the yearly plan (P11)
    audit.record("system", "fund.allocated", None, **{k: str(v) for k, v in result.items()})
    return result
