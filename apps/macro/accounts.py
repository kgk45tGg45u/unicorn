"""Hours by use: where the paid hours of a month went (docs/03 section 3, book 4-1 to 4-10).

All amounts are hours = UNIQ. The hours identity is not exactly zero, because prices use declared or measured hours,
not the exact hours of each item: the residual is stored and warned about when it passes 2% of the hours paid.
"""

from datetime import datetime, time
from decimal import Decimal

from django.db.models import Sum
from django.utils.translation import gettext as _

from apps.core.money import uniq
from apps.ledger.models import Account, Entry
from apps.ledger.services import BERLIN

ZERO = Decimal("0.0000")
TOLERANCE = Decimal("0.02")


def _bounds(period):
    first = datetime.combine(datetime(period.year, period.month, 1).date(), time.min, tzinfo=BERLIN)
    year, month = (period.year + 1, 1) if period.month == 12 else (period.year, period.month + 1)
    return first, datetime.combine(datetime(year, month, 1).date(), time.min, tzinfo=BERLIN)


def _sum(qs, field="amount"):
    return qs.aggregate(t=Sum(field))["t"] or ZERO


def flows(period) -> dict:
    """The UNIQ flows of the period, from the ledger."""
    entries = Entry.objects.filter(transaction__period=period)
    gross = _sum(entries.filter(transaction__kind="hours_pay", amount__gt=0))
    tax = _sum(entries.filter(transaction__kind="tax", account__kind=Account.FUND2))
    transfers = _sum(entries.filter(transaction__kind="transfer", amount__gt=0))
    spent = _sum(entries.filter(transaction__kind__in=("purchase", "rent"), account__kind=Account.FUND1))
    cancelled = _sum(entries.filter(transaction__kind="cancel", account__kind=Account.FUND2))
    return {
        "hours_paid": gross,
        "tax": tax,
        "net_issued": gross - tax,
        "transfers": transfers,
        "spent": spent,
        "cancelled": cancelled,
    }


def _paid_minutes(period, **filters):
    from apps.units.models import HoursEntry

    total = HoursEntry.objects.filter(period=period, status="paid", **filters).aggregate(t=Sum("minutes"))["t"] or 0
    return uniq(Decimal(total) / 60)


def depreciation_per_unit(offer) -> Decimal:
    """Hours of Unicorn-owned tools worn out per unit made (the engine's d_j)."""
    q = offer.batch_size if offer.batch_size else Decimal(1)
    total = Decimal(0)
    for t in offer.tools.all():
        if t.source == "unicorn_owned" and t.lifetime_uses:
            total += t.value_uniq / t.lifetime_uses * t.uses_per_batch / q
    return total


def _delivered_value(period, purpose):
    """The labour value of production orders with this purpose that were completed in the period."""
    from apps.market.models import ProductionOrder

    start, end = _bounds(period)
    total = Decimal(0)
    for po in ProductionOrder.objects.filter(
        status="done", purpose=purpose, done_at__gte=start, done_at__lt=end
    ).select_related("offer"):
        total += (po.quantity_done if po.quantity_done is not None else po.quantity) * po.offer.value_total
    return uniq(total)


def _outside_lines_value(period, start, end):
    """The hours inside the outside order lines delivered in the period (docs/03 section 3: Trade)."""
    from apps.market.models import OrderLine

    total = OrderLine.objects.filter(
        order__kind="outside", status="delivered", delivered_at__gte=start, delivered_at__lt=end
    ).aggregate(t=Sum("value_at_order"))["t"]
    return uniq(total or Decimal(0))


def inventory_value() -> Decimal:
    """Products on the shelves at their labour value, plus the approved hours inside unfinished production orders."""
    from apps.market.models import ProductionOrder, StockLot
    from apps.units.models import HoursEntry

    total = Decimal(0)
    for lot in StockLot.objects.filter(status="available").select_related("offer"):
        total += lot.quantity_left * lot.offer.value_total
    open_ids = [
        str(i) for i in ProductionOrder.objects.filter(status__in=("open", "started")).values_list("id", flat=True)
    ]
    if open_ids:
        minutes = (
            HoursEntry.objects.filter(
                ref_type="productionorder", ref_id__in=open_ids, status__in=("approved", "paid")
            ).aggregate(t=Sum("minutes"))["t"]
            or 0
        )
        total += Decimal(minutes) / 60
    return uniq(total)


def hours_by_use(period, previous_inventory=ZERO) -> dict:
    """The seven uses of the hours, the depreciation, the stock change and the residual (book 4-1, 4-10)."""
    from apps.market.models import OrderLine, ServiceSlot, WasteRecord

    f = flows(period)
    start, end = _bounds(period)
    social = _paid_minutes(period, unit__kind__in=("social", "coordination"))
    accumulation = _delivered_value(period, "accumulation") + _paid_minutes(period, unit__mode="project")
    trade = _outside_lines_value(period, start, end)
    idle = (
        ServiceSlot.objects.filter(status="done", starts_at__gte=start, starts_at__lt=end).aggregate(
            t=Sum("idle_minutes")
        )["t"]
        or 0
    )
    waste = _sum(WasteRecord.objects.filter(period=period), "hours") + uniq(Decimal(idle) / 60)
    depreciation = Decimal(0)
    for line in OrderLine.objects.filter(
        status="delivered", delivered_at__gte=start, delivered_at__lt=end
    ).select_related("offer"):
        depreciation += line.quantity * depreciation_per_unit(line.offer)
    stock = inventory_value()
    change = stock - previous_inventory
    consumption = f["spent"]
    used = consumption + social + accumulation + trade + waste + change
    residual = uniq(f["hours_paid"] + depreciation - used)
    return {
        **f,
        "consumption": consumption,
        "social": social,
        "accumulation": uniq(accumulation),
        "trade": trade,
        "waste": uniq(waste),
        "depreciation": uniq(depreciation),
        "inventory_change": uniq(change),
        "inventory_value": stock,
        "hours_residual": residual,
        "residual_warning": bool(f["hours_paid"]) and abs(residual) > f["hours_paid"] * TOLERANCE,
    }


RESIDUAL_WORDS = _("The recipes and the real hours have drifted apart.")
