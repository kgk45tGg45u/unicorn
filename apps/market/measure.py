"""Measured hours, supply weights, plausibility checks and close checks (docs/04 sections 6 and 10)."""

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.catalogue import services as catalogue
from apps.core import audit
from apps.core.money import uniq
from apps.rules.services import get_param
from apps.units import services as unit_services

from .models import Booking, InputRequest, OrderLine, PlausibilityRecord, ProductionOrder, Sale, ServiceSlot
from .services import BERLIN, _months_ago, today

APPROVED = ("approved", "pending_sale", "paid")


def _start_of_day(day):
    from datetime import datetime

    return datetime(day.year, day.month, day.day, tzinfo=BERLIN)


def _sum(rows) -> Decimal:
    return rows.aggregate(t=Sum("quantity"))["t"] or Decimal("0")


def units_delivered(offer, start: date, end: date) -> Decimal:
    """Units of the offer delivered from `start` up to (not including) `end`: to members, in person and to other units.

    For a service this is the customers served.
    """
    a, b = _start_of_day(start), _start_of_day(end)
    if offer.is_service:
        served = Booking.objects.filter(slot__offer=offer, status="confirmed", confirmed_at__gte=a, confirmed_at__lt=b)
        return Decimal(served.count())
    lines = OrderLine.objects.filter(offer=offer, status="delivered", delivered_at__gte=a, delivered_at__lt=b)
    sales = Sale.objects.filter(offer=offer, status="paid", paid_at__gte=a, paid_at__lt=b)
    inputs = InputRequest.objects.filter(
        supplier_offer=offer, status__in=["delivered", "received"], delivered_at__gte=a, delivered_at__lt=b
    )
    return _sum(lines) + _sum(sales) + _sum(inputs)


def approved_minutes(offer, start: date, end: date) -> int:
    """Approved minutes of hours entries linked to the offer's production orders or sessions, by the entry's date."""
    from apps.units.models import HoursEntry

    refs = {
        "production_order": [str(i) for i in ProductionOrder.objects.filter(offer=offer).values_list("pk", flat=True)],
        "slot": [str(i) for i in ServiceSlot.objects.filter(offer=offer).values_list("pk", flat=True)],
    }
    total = 0
    for ref_type, ids in refs.items():
        if ids:
            total += (
                HoursEntry.objects.filter(
                    unit=offer.unit,
                    ref_type=ref_type,
                    ref_id__in=ids,
                    status__in=APPROVED,
                    date__gte=start,
                    date__lt=end,
                ).aggregate(t=Sum("minutes"))["t"]
                or 0
            )
    return total


def measured_hours(offer):
    """Hours per unit measured over the last months, or None while there is too little data."""
    start = _months_ago(get_param("catalogue.measure_window_months")).astimezone(BERLIN).date()
    end = today() + timedelta(days=1)
    minutes = approved_minutes(offer, start, end)
    units = units_delivered(offer, start, end)
    if (
        Decimal(minutes) / 60 < get_param("catalogue.measure_min_hours")
        or units < get_param("catalogue.measure_min_units")
        or units <= 0
    ):
        return None
    return uniq(Decimal(minutes) / 60 / units)


def supply_weights(offers_by_item):
    """Each offer's share of its item's deliveries over the window; equal shares if nothing was delivered."""
    start = _months_ago(get_param("catalogue.measure_window_months")).astimezone(BERLIN).date()
    end = today() + timedelta(days=1)
    weights = {}
    for item_id, offers in offers_by_item.items():
        delivered = {o.pk: units_delivered(o, start, end) for o in offers}
        total = sum(delivered.values(), Decimal("0"))
        if total <= 0:
            weights[item_id] = {o.pk: 1 / len(offers) for o in offers}
        else:
            weights[item_id] = {pk: float(q / total) for pk, q in delivered.items()}
    return weights


# --- The monthly plausibility checks (HF-15: notices, never refusals) ---


def _month_bounds(month: date):
    first = month.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    return first, nxt


def _previous_month(day):
    return (day.replace(day=1) - timedelta(days=1)).replace(day=1)


def _streak(offer, kind, month, months):
    """True when the offer was flagged in each of the last `months` months, this one included."""
    m = month
    for _i in range(months):
        if not PlausibilityRecord.objects.filter(offer=offer, month=m, kind=kind, flagged=True).exists():
            return False
        m = _previous_month(m)
    return True


def _notice(offer, record, verb, **data):
    audit.record("system", verb, offer, month=f"{record.month:%Y-%m}", value=str(record.value), **data)
    record.notified = True
    record.save(update_fields=["notified"])


def check_offer(offer, month: date):
    start, end = _month_bounds(month)
    units = units_delivered(offer, start, end)
    if units <= 0:
        return
    deviation = get_param("governance.plausibility.deviation")
    months = get_param("governance.plausibility.months")

    # hours against output
    minutes = approved_minutes(offer, start, end)
    if minutes and offer.value_direct > 0:
        per_unit = Decimal(minutes) / 60 / units
        gap = abs(per_unit - offer.value_direct) / offer.value_direct
        record, _created = PlausibilityRecord.objects.update_or_create(
            offer=offer, month=start, kind="hours", defaults={"value": uniq(gap), "flagged": gap > deviation}
        )
        if record.flagged and _streak(offer, "hours", start, months) and not record.notified:
            recent = PlausibilityRecord.objects.filter(
                offer=offer, kind="hours", notified=True, month__gte=_back(start, months)
            )
            if not recent.exists():
                _notice(offer, record, "plausibility.hours_gap", months=months)

    # inputs against output
    worst = Decimal("0")
    for row in offer.inputs.filter(source="unicorn"):
        expected = row.quantity_per_batch / (offer.batch_size or 1) * units
        got = InputRequest.objects.filter(
            production_order__offer=offer,
            offer_input=row,
            status="received",
            received_at__gte=_start_of_day(start),
            received_at__lt=_start_of_day(end),
        ).aggregate(t=Sum("quantity"))["t"] or Decimal("0")
        if expected > 0:
            worst = max(worst, got / expected)
    if worst > 0:
        record, _created = PlausibilityRecord.objects.update_or_create(
            offer=offer, month=start, kind="inputs", defaults={"value": uniq(worst), "flagged": worst > Decimal("1.3")}
        )
        if record.flagged and not record.notified:
            _notice(offer, record, "plausibility.inputs_high")


def _back(month, months):
    m = month
    for _i in range(months - 1):
        m = _previous_month(m)
    return m


def run_plausibility(month: date | None = None):
    """Check every active offer for one month (default: the last full month). Safe to run twice."""
    month = (month or _previous_month(today())).replace(day=1)
    count = 0
    for offer in (
        catalogue.Offer.objects.filter(status="active").select_related("item", "unit").prefetch_related("inputs")
    ):
        check_offer(offer, month)
        count += 1
    return count


# --- Closing a unit ---


def close_check(unit) -> list:
    """Reasons that stop a unit from closing: open batches, and future sessions with bookings."""
    reasons = []
    open_orders = ProductionOrder.objects.filter(offer__unit=unit, status__in=["open", "started"]).count()
    if open_orders:
        reasons.append(_("%(n)s production orders are still open. Finish or cancel them first.") % {"n": open_orders})
    booked = (
        ServiceSlot.objects.filter(offer__unit=unit, starts_at__gt=timezone.now(), bookings__status="booked")
        .distinct()
        .count()
    )
    if booked:
        reasons.append(_("%(n)s coming sessions still have bookings. Cancel them first.") % {"n": booked})
    return reasons


def register():
    catalogue.MEASURED_HOURS_HOOK = measured_hours
    catalogue.SUPPLY_WEIGHTS_HOOK = supply_weights
    if close_check not in unit_services.CLOSE_CHECKS:
        unit_services.CLOSE_CHECKS.append(close_check)
