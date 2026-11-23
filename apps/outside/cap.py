"""The cap on outside-sales hours (docs/07 section 6). It applies a limit the plan already decided."""

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.notify import notify
from apps.rules.services import get_param


def _month_bounds(today):
    first = today.replace(day=1)
    return first, (first + timedelta(days=32)).replace(day=1)


def outside_hours_this_month(today=None) -> Decimal:
    """The hours inside the outside order lines due this month."""
    from apps.market.models import OrderLine

    first, nxt = _month_bounds(today or timezone.localdate())
    total = (
        OrderLine.objects.filter(order__kind="outside", due_date__gte=first, due_date__lt=nxt)
        .exclude(status="cancelled")
        .aggregate(t=Sum("value_at_order"))["t"]
    )
    return total or Decimal(0)


def expected_hours():
    """The hours expected this month: the last close's H, else the plan's figure, else the last hours paid."""
    from apps.ledger.services import current_period
    from apps.macro.models import MacroSnapshot

    period = current_period()
    if period.planned_hours > 0:
        return period.planned_hours
    snap = MacroSnapshot.objects.first()
    if snap is not None:
        h = (snap.tax_inputs or {}).get("H")
        return Decimal(str(h)) if h else snap.hours_paid
    return None


def cap_hours():
    h = expected_hours()
    return None if not h else Decimal(str(get_param("economy.outside_sales_cap_share"))) * h


def earliest_date(offer, quantity, today=None) -> date:
    """The day the order can be ready: the unit's lead time, or the first of next month when this month is full."""
    from apps.catalogue import services as catalogue

    today = today or timezone.localdate()
    ready = today + timedelta(days=catalogue.lead_time_days(offer))
    cap = cap_hours()
    if cap is None:
        return ready
    first, nxt = _month_bounds(today)
    if ready < nxt and outside_hours_this_month(today) + offer.value_total * Decimal(str(quantity)) > cap:
        return nxt
    return ready


def moved_to_next_month(offer, quantity, due, lead_days, today=None) -> bool:
    today = today or timezone.localdate()
    return due > today + timedelta(days=lead_days)


def tell_unit(offer):
    from apps.units import services as unit_services

    for w in unit_services.workers(offer.unit).select_related("member"):
        notify(
            w.member,
            _("The plan's cap on outside sales is full this month. New outside orders for %(item)s start next month.")
            % {"item": offer.item.name},
            f"/units/{offer.unit.slug}/",
        )
