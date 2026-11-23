"""The tax balance (docs/03 section 4, book p. 88).

    (1 - tau) * H + T = C + S*      so      tau = 1 - (C + S* - T) / H

H: hours expected to be paid next month. C: hours inside the goods and services members will buy. T: transfers
due next month. S*: the expected change in members' savings. The result is clipped to the hard bounds (HF-9).
"""

from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal

from django.db.models import Sum
from django.utils.translation import gettext as _

from apps.core.money import uniq
from apps.ledger.models import Account, Entry, Period
from apps.members.models import Member
from apps.rules.services import get_param

# from ../Unicorn-simulation config/seed.yaml members.savings
SAVING_RATE = Decimal("0.05")  # a member below target saves this share of their average monthly net income
SPEND_DOWN_RATE = Decimal("0.10")  # a member above target spends this share of the excess
EX_SPEND_SHARE = Decimal("0.05")  # former members spend this share of their balances
Q4 = Decimal("0.0001")
ZERO = Decimal("0.0000")


def _next_month(period) -> date:
    return date(period.year + (period.month == 12), 1 if period.month == 12 else period.month + 1, 1)


def _previous_periods(period, n):
    older = Period.objects.filter(year__lt=period.year) | Period.objects.filter(
        year=period.year, month__lt=period.month
    )
    return list(older.order_by("-year", "-month")[:n])


def tax_from_inputs(h, c, s_star, t) -> Decimal:
    """The balance formula, clipped to the hard bounds. H must be above zero."""
    tau = 1 - (c + s_star - t) / h
    low, high = Decimal(str(get_param("economy.flat_tax.min"))), Decimal(str(get_param("economy.flat_tax.max")))
    return min(max(tau.quantize(Q4, rounding=ROUND_HALF_EVEN), low), high)


def expected_hours(period, flows, months=3) -> Decimal:
    """H: the average gross hours of the last `months` closed periods (this one included)."""
    from .models import MacroSnapshot

    values = [flows["hours_paid"]]
    for p in _previous_periods(period, months - 1):
        snap = MacroSnapshot.objects.filter(period=p).first()
        if snap is not None:
            values.append(snap.hours_paid)
    if len(values) >= months:
        return uniq(sum(values, Decimal(0)) / len(values))
    planned = Period.objects.filter(year=_next_month(period).year, month=_next_month(period).month).first()
    if planned is not None and planned.planned_hours > 0:
        return planned.planned_hours  # in the first months: the plan's figure, else the last period's hours
    return uniq(flows["hours_paid"])


def _spent_by_ref(period):
    """UNIQ spent in a period on bookings and stock purchases, and on rents (docs/03 section 4, C)."""
    from apps.market.models import OrderLine

    entries = Entry.objects.filter(transaction__period=period, account__kind=Account.FUND1)
    rents = entries.filter(transaction__kind="rent").aggregate(t=Sum("amount"))["t"] or ZERO
    total = ZERO
    for e in entries.filter(transaction__kind="purchase").select_related("transaction"):
        kind, ref = e.transaction.ref_type, e.transaction.ref_id
        if kind in ("booking", "sale"):
            total += e.amount
        elif kind == "orderline" and OrderLine.objects.filter(pk=ref, stock_lot__isnull=False).exists():
            total += e.amount
    return total, rents


def expected_consumption(period, months=3) -> Decimal:
    """C: undelivered member order lines due next month, plus the recent average of bookings, stock purchases, rents."""
    from apps.market.models import OrderLine

    first = _next_month(period)
    after = _next_month(Period(year=first.year, month=first.month))
    on_hand = (
        OrderLine.objects.filter(
            status__in=("placed", "from_stock", "in_production", "ready", "handed_over"),
            due_date__gte=first,
            due_date__lt=after,
        ).aggregate(t=Sum("total_uniq"))["t"]
        or ZERO
    )
    periods = [period, *_previous_periods(period, months - 1)]
    pairs = [_spent_by_ref(p) for p in periods]
    average = sum((a + b for a, b in pairs), ZERO) / len(pairs)
    return uniq(on_hand + average)


def expected_savings_change(period, months=6) -> Decimal:
    """S*: members below their savings target add to their savings, members above it spend some, former members too."""
    target_months = Decimal(str(get_param("economy.savings_target_months")))
    periods = [period, *_previous_periods(period, months - 1)]
    total = ZERO
    for m in Member.objects.filter(status__in=("member", "former"), deleted=False):
        accounts = Account.objects.filter(member=m, kind=Account.MEMBER).first()
        if accounts is None:
            continue
        rows = Entry.objects.filter(account=accounts, transaction__period__in=periods)
        spending = -(rows.filter(transaction__kind__in=("purchase", "rent")).aggregate(t=Sum("amount"))["t"] or ZERO)
        income = (
            rows.filter(transaction__kind__in=("hours_pay", "tax", "transfer")).aggregate(t=Sum("amount"))["t"] or ZERO
        )
        balance = Entry.objects.filter(account=accounts).aggregate(t=Sum("amount"))["t"] or ZERO
        n = len(periods)
        if m.status == "former":
            total -= EX_SPEND_SHARE * balance
            continue
        target = target_months * spending / n
        if balance < target:
            total += SAVING_RATE * income / n
        else:
            total -= SPEND_DOWN_RATE * (balance - target)
    return uniq(total)


def next_tax_rate(period, flows) -> tuple[Decimal, dict]:
    """The flat tax of the next month and the inputs that gave it, by `economy.flat_tax.method`."""
    method = get_param("economy.flat_tax.method")
    current = Decimal(str(period.tax_rate))
    inputs = {"method": method}
    if method == "fixed":
        rate = Decimal(str(get_param("economy.flat_tax.fixed_rate")))
        return rate, {**inputs, "fixed_rate": str(rate)}
    if method == "balance_yearly" and period.month != 12:
        return current, {**inputs, "note": _("The rate is set once a year, at the December close.")}
    months = 12 if method == "balance_yearly" else 3
    h = expected_hours(period, flows, months)
    inputs["H"] = str(h)
    if h <= 0:
        return current, {**inputs, "note": _("No hours were paid, so the rate stays.")}
    c = expected_consumption(period, months)
    s = expected_savings_change(period)
    from . import transfers

    t = transfers.due_next_month(period)
    rate = tax_from_inputs(h, c, s, t)
    return rate, {**inputs, "C": str(c), "S": str(s), "T": str(t), "tau": str(rate)}


EXPLANATION = _(
    "Each month the flat tax for the next month is set so that what members earn after tax, plus transfers, equals "
    "what they are expected to buy plus the change in their savings: tax = 1 - (C + S - T) / H. H is the hours "
    "expected to be paid, C the hours inside what members will buy, S the expected change in savings, T the "
    "transfers due. Waste raises it, because hours of products nobody buys are in H but not in C."
)
