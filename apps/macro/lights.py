"""The warning lights (docs/03 section 10). Each light has a value, a colour and one plain sentence.

Colours: green, amber, red, and grey (not measured). The words always say the colour too, for colour-blind members.
"""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.rules.services import get_param

GREEN, AMBER, RED, GREY = "green", "amber", "red", "grey"
COLOUR_WORDS = {GREEN: _("green"), AMBER: _("amber"), RED: _("red"), GREY: _("not measured")}


def _light(value, color, text):
    return {
        "value": None if value is None else str(value),
        "color": color,
        "word": str(COLOUR_WORDS[color]),
        "text": str(text),
    }


def _p(key):
    return Decimal(str(get_param(key)))


def _previous(period, n):
    from apps.ledger.models import Period

    older = Period.objects.filter(year__lt=period.year) | Period.objects.filter(
        year=period.year, month__lt=period.month
    )
    return [period, *older.order_by("-year", "-month")[: n - 1]]


def unspent_uniq(period):
    """Members' and former members' balances (without retirement accounts) over their average monthly spending."""
    from apps.ledger.models import Account, Entry

    balance = Entry.objects.filter(account__kind=Account.MEMBER).aggregate(t=Sum("amount"))["t"] or Decimal(0)
    periods = _previous(period, 6)
    spent = -(
        Entry.objects.filter(
            account__kind=Account.MEMBER, transaction__period__in=periods, transaction__kind__in=("purchase", "rent")
        ).aggregate(t=Sum("amount"))["t"]
        or Decimal(0)
    )
    average = spent / len(periods)
    if average <= 0:
        return _light(None, GREY, _("Not measured yet: nothing was spent in the last months."))
    months = (balance / average).quantize(Decimal("0.01"))
    amber = _p("alarms.unspent_uniq_amber_months")
    red = amber * _p("alarms.unspent_uniq_red_multiple")
    color = RED if months > red else AMBER if months > amber else GREEN
    text = _("Unspent UNIQ equal %(months)s months of spending (%(color)s above %(amber)s).") % {
        "months": months,
        "color": COLOUR_WORDS[color],
        "amber": amber,
    }
    return _light(months, color, text)


def _lines_due(period):
    from apps.market.models import OrderLine

    return OrderLine.objects.filter(due_date__year=period.year, due_date__month=period.month).exclude(
        status__in=("cancelled", "refused")
    )


def _served(lines):
    done = 0
    for line in lines:
        if line.status == "delivered" and line.delivered_at is not None and line.delivered_at.date() <= line.due_date:
            done += 1
    return done


def shelves(period):
    """Order lines delivered by their due date over the lines due; waiting-list entries count as not served."""
    from apps.market.models import WaitingListEntry

    lines = list(_lines_due(period))
    waiting = WaitingListEntry.objects.filter(created_at__year=period.year, created_at__month=period.month).count()
    total = len(lines) + waiting
    if total == 0:
        return _light(None, GREY, _("Not measured yet: nothing was due this month."))
    share = (Decimal(_served(lines)) / total).quantize(Decimal("0.0001"))
    color = RED if share < _p("alarms.shelves_red") else AMBER if share < _p("alarms.shelves_amber") else GREEN
    return _light(
        share,
        color,
        _("Members got %(share)s%% of what they ordered in time (%(color)s).")
        % {"share": (share * 100).quantize(Decimal("1")), "color": COLOUR_WORDS[color]},
    )


def unsold(period):
    """Written-off value over the value of products made ahead or on the unit's own initiative in 3 months."""
    from apps.market.models import StockLot, WasteRecord

    periods = _previous(period, 3)
    waste = WasteRecord.objects.filter(period__in=periods).aggregate(t=Sum("hours"))["t"] or Decimal(0)
    since = timezone.now() - timedelta(days=92)
    made = sum(
        (
            lot.quantity * lot.offer.value_total
            for lot in StockLot.objects.filter(
                origin__in=("advance", "own_initiative"), made_at__gte=since
            ).select_related("offer")
        ),
        Decimal(0),
    )
    if made <= 0:
        return _light(None, GREY, _("Not measured yet: no products were made ahead."))
    share = (waste / made).quantize(Decimal("0.0001"))
    color = RED if share > _p("alarms.unsold_red") else AMBER if share > _p("alarms.unsold_amber") else GREEN
    return _light(
        share,
        color,
        _("%(share)s%% of the products made ahead were written off (%(color)s).")
        % {"share": (share * 100).quantize(Decimal("1")), "color": COLOUR_WORDS[color]},
    )


def euro_reserve(period):
    from apps.tradefund import allocation

    months = allocation.reserve_months()
    if months is None:
        return _light(None, GREY, _("Not measured yet: the trade fund has paid nothing out so far."))
    color = (
        RED
        if months < _p("alarms.euro_reserve_red_months")
        else AMBER
        if months < _p("alarms.euro_reserve_amber_months")
        else GREEN
    )
    return _light(
        months,
        color,
        _("The trade fund holds %(months)s months of outgoings (%(color)s).")
        % {"months": months, "color": COLOUR_WORDS[color]},
    )


def idle_shifts(period):
    from apps.market.models import ServiceSlot

    if get_param("economy.services.pay_rule") == "when_performed":
        return _light(None, GREY, _("Not used: services are paid only when they are performed."))
    slots = ServiceSlot.objects.filter(status="done", starts_at__year=period.year, starts_at__month=period.month)
    session = sum(((s.ends_at - s.starts_at).total_seconds() / 60 for s in slots), 0)
    if session <= 0:
        return _light(None, GREY, _("Not measured yet: no sessions this month."))
    share = (Decimal(sum(s.idle_minutes for s in slots)) / Decimal(session)).quantize(Decimal("0.0001"))
    color = RED if share > _p("alarms.idle_shifts_red") else AMBER if share > _p("alarms.idle_shifts_amber") else GREEN
    return _light(
        share,
        color,
        _("%(share)s%% of paid shift time had no customers (%(color)s).")
        % {"share": (share * 100).quantize(Decimal("1")), "color": COLOUR_WORDS[color]},
    )


def street_price(period):
    if not get_param("alarms.street_price_enabled"):
        return _light(None, GREY, _("Not measured yet: members have not decided what it is based on."))
    return _light(None, GREY, _("The street price is switched on, but its basis is not decided."))


def compute_lights(period) -> dict:
    return {
        "unspent": unspent_uniq(period),
        "shelves": shelves(period),
        "unsold": unsold(period),
        "euro_reserve": euro_reserve(period),
        "idle_shifts": idle_shifts(period),
        "street_price": street_price(period),
    }


# --- Per item: the shortage cap (docs/03 section 9; P05.T01) ---


def item_red(item) -> bool:
    """True while this item's own shelves ratio this month is below the red level."""
    from apps.ledger.services import current_period
    from apps.market.models import OrderLine

    period = current_period()
    lines = list(
        OrderLine.objects.filter(offer__item=item, due_date__year=period.year, due_date__month=period.month).exclude(
            status__in=("cancelled", "refused")
        )
    )
    if not lines:
        return False
    share = Decimal(_served(lines)) / len(lines)
    return share < _p("alarms.shelves_red")


# --- The credit line (docs/03 section 2; book p. 58) ---


def credit_line_check(period, hours_paid):
    """More hours paid than planned (plus the tolerance) opens a question ticket. Nothing is ever stopped (HF-15)."""
    from apps.core.notify import notify
    from apps.tickets import services as ticket_services
    from apps.units.models import HoursEntry
    from apps.votes.elections import current_members

    planned = period.planned_hours
    if planned <= 0:
        return None
    limit = planned * (1 + _p("economy.issue_tolerance_share"))
    if hours_paid <= limit:
        return None
    previous = _previous(period, 2)[1:]
    grown = []
    for unit_id in HoursEntry.objects.filter(period=period, status="paid").values_list("unit", flat=True).distinct():
        now = (
            HoursEntry.objects.filter(period=period, unit_id=unit_id, status="paid").aggregate(t=Sum("minutes"))["t"]
            or 0
        )
        before = (
            HoursEntry.objects.filter(period__in=previous, unit_id=unit_id, status="paid").aggregate(t=Sum("minutes"))[
                "t"
            ]
            or 0
        )
        grown.append((now - before, unit_id))
    from apps.units.models import Unit

    top = [Unit.objects.get(pk=u).name for g, u in sorted(grown, reverse=True)[:5] if g > 0]
    month = f"{period.year}-{period.month:02d}"
    ticket = ticket_services.create_ticket(
        "question",
        None,
        _("More hours were paid than planned in %(month)s") % {"month": month},
        body=_("%(paid)s hours were paid. The plan expected %(planned)s. The units whose hours grew most: %(units)s.")
        % {"paid": hours_paid, "planned": planned, "units": ", ".join(top) or "-"},
        scope="all",
    )
    for member in current_members("auditor"):
        notify(
            member,
            _("More hours were paid than planned in %(month)s.") % {"month": month},
            f"/tickets/{ticket.number}/",
        )
    return ticket


def refresh_cache(period=None):
    """Daily: the lights of the current period, stored so that pages do not wait for the month's end."""
    from apps.ledger.services import current_period

    from .models import LightsCache

    period = period or current_period()
    row, _created = LightsCache.objects.update_or_create(period=period, defaults={"lights": compute_lights(period)})
    return row


def latest() -> dict:
    """The lights to show: today's cache, or the last close, or an empty set."""
    from .models import LightsCache, MacroSnapshot

    cache = LightsCache.objects.order_by("-period__year", "-period__month").first()
    if cache is not None:
        return cache.lights
    snap = MacroSnapshot.objects.first()
    return snap.lights if snap else {}
