"""World metrics, the planning rate and attractiveness (docs/03 sections 8 and 10).

They measure how close the real world is to the conditions of the simulation's successful world (docs/02 section 5).
Outside sales come from phase 10; until then they are zero and the planning rate uses its fallback.
"""

import csv
import statistics
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.rules.services import get_param

ZERO = Decimal(0)
BENCHMARK = Path(settings.BASE_DIR) / "config" / "benchmarks" / "default_world_path.csv"


def _outside():
    """The outside-sales numbers, or None before phase 10 exists."""
    try:
        from apps.outside import services as outside
    except ImportError:
        return None
    return outside


def active_members() -> int:
    from apps.members.models import Member

    return Member.objects.filter(status="member", deleted=False).count()


def _eur_paid_for_materials(period) -> Decimal:
    from apps.tradefund import fx, public
    from apps.tradefund.models import FundEntry

    total = ZERO
    for e in FundEntry.objects.filter(kind="payment_out", created_at__year=period.year, created_at__month=period.month):
        if public.category_of(e) == "materials":
            total += fx.to_eur(-e.amount, e.currency)
    return total


def materials_eur_per_hour(period):
    from apps.units.models import HoursEntry

    minutes = (
        HoursEntry.objects.filter(period=period, status="paid", unit__kind__in=("production", "service")).aggregate(
            t=Sum("minutes")
        )["t"]
        or 0
    )
    if not minutes:
        return None
    return (_eur_paid_for_materials(period) / (Decimal(minutes) / 60)).quantize(Decimal("0.0001"))


def can_live_without_job_share():
    """Members who say they have no capitalist job, or whose active benefit claim covers their basic bills."""
    from apps.members.models import Member
    from apps.tradefund.models import BenefitClaim

    members = Member.objects.filter(status="member", deleted=False)
    n = members.count()
    if not n:
        return None
    covered = set(BenefitClaim.objects.filter(status="active").values_list("member_id", flat=True))
    free = set(members.filter(has_capitalist_job=False).values_list("pk", flat=True))
    return (Decimal(len(covered | free)) / n).quantize(Decimal("0.0001"))


# --- The planning rate (docs/03 section 8) ---


def measured_planning_rate():
    """Euros earned per outside-sales hour after the sellers' tax reserves, or None until 3 months of data exist."""
    outside = _outside()
    if outside is None:
        return None
    months = get_param("economy.planning_rate.measure_months")
    euros, hours, covered = outside.sales_after_tax_and_hours(months)
    if covered < 3 or not hours:
        return None
    return (euros / hours).quantize(Decimal("0.01"))


def planning_rate() -> Decimal:
    rate = measured_planning_rate() if get_param("economy.planning_rate.method") == "measured_outside_sales" else None
    return rate if rate is not None else Decimal(str(get_param("economy.planning_rate.fallback_eur_per_hour")))


# --- Attractiveness: an hour in Unicorn against an hour at a capitalist wage ---

MIN_MEMBERS_WITH_WAGE = 10
MIN_OFFERS_WITH_PRICE = 5


def uniq_value_eur():
    """The euro value of a UNIQ: outside prices over labour values of the offers sold outside, weighted by purchases."""
    from datetime import timedelta

    from apps.catalogue.models import Offer
    from apps.market.models import OrderLine

    since = timezone.now() - timedelta(days=92)
    offers = list(Offer.objects.filter(outside_price__isnull=False, value_total__gt=0, status="active"))
    if len(offers) < MIN_OFFERS_WITH_PRICE:
        return None
    num = den = ZERO
    for o in offers:
        weight = OrderLine.objects.filter(offer=o, created_at__gte=since).aggregate(t=Sum("total_uniq"))[
            "t"
        ] or Decimal(1)
        num += weight * (o.outside_price / o.value_total)
        den += weight
    return num / den if den else None


def attractiveness_estimate(period=None):
    """The median over members who stated a wage of (net UNIQ per hour x the euro value of a UNIQ) / wage."""
    # OWNER-CHECK: estimate method. The euro value of a UNIQ is an estimate for comparing only (HF-4).
    from apps.ledger.services import current_period
    from apps.members import services as member_services
    from apps.members.models import Member

    value = uniq_value_eur()
    if value is None:
        return None
    period = period or current_period()
    net_per_hour = 1 - Decimal(str(period.tax_rate))
    ratios = []
    for m in Member.objects.filter(status="member", deleted=False):
        wage = member_services.get_private(m).get("net_hourly_wage_eur")
        try:
            wage = Decimal(str(wage))
        except Exception:  # noqa: BLE001  no wage stated, or not a number
            continue
        if wage > 0:
            ratios.append(net_per_hour * value / wage)
    if len(ratios) < MIN_MEMBERS_WITH_WAGE:
        return None
    return Decimal(str(statistics.median(ratios))).quantize(Decimal("0.0001"))


# --- The world, as stored at each close ---


def world_metrics(period) -> dict:
    from .models import MacroSnapshot

    members = active_members()
    outside = _outside()
    sales = outside.confirmed_sales_eur(period.year, period.month) if outside else ZERO
    per_member = (sales / members).quantize(Decimal("0.01")) if members else ZERO
    growth = None
    older = MacroSnapshot.objects.filter(period__year=period.year - 1, period__month=period.month).first()
    before = (older.world or {}).get("outside_sales_per_member_eur") if older else None
    if before and Decimal(str(before)) > 0:
        growth = ((per_member - Decimal(str(before))) / Decimal(str(before))).quantize(Decimal("0.0001"))
    from . import lights

    unsold = lights.unsold(period)["value"]
    data = {
        "members": members,
        "outside_sales_per_member_eur": per_member,
        "outside_growth_12m": growth,
        "materials_eur_per_hour": materials_eur_per_hour(period),
        "tax_on_outside_sales_share": outside.tax_share(period.year, period.month) if outside else None,
        "unsold_share": Decimal(unsold) if unsold is not None else None,
        "can_live_without_job_share": can_live_without_job_share(),
        "planning_rate_eur_per_hour": planning_rate(),
        "attractiveness_estimate": attractiveness_estimate(period),
        "reserve_months": _reserve_months(),
    }
    return {k: (None if v is None else str(v)) for k, v in data.items()}


def _reserve_months():
    from apps.tradefund import allocation

    return allocation.reserve_months()


# --- "Are we on track?" (docs/02 section 5) ---


def benchmark_rows():
    """The default world's path, month by month, from config/benchmarks/default_world_path.csv."""
    with BENCHMARK.open(newline="") as f:
        lines = [line for line in f if not line.startswith("#")]
    return list(csv.DictReader(lines))


def months_since_launch(today=None) -> int:
    from apps.members.models import SiteState

    launched = SiteState.get().launched_at
    today = today or timezone.localdate()
    if launched is None:
        return 1
    start = timezone.localtime(launched).date()
    return max(1, (today.year - start.year) * 12 + today.month - start.month + 1)


def verdict(real, target):
    """'on track', 'behind' (below 75% of the default world's value) or 'far behind' (below 40%)."""
    if real is None or target is None:
        return "unknown"
    real, target = Decimal(str(real)), Decimal(str(target))
    if target <= 0:
        return "on_track"
    ratio = real / target
    return "on_track" if ratio >= Decimal("0.75") else "behind" if ratio >= Decimal("0.40") else "far_behind"


VERDICT_WORDS = {
    "on_track": _("on track"),
    "behind": _("behind"),
    "far_behind": _("far behind"),
    "unknown": _("not measured yet"),
}


def on_track(real: dict, month_index: int):
    """One row per condition: the real value, the target, the default world's value for the same month, a verdict."""
    rows = benchmark_rows()
    row = rows[min(month_index, len(rows)) - 1]
    f = lambda key: Decimal(row[key])  # noqa: E731
    spec = [
        (
            _("Outside sales per member and month (euros)"),
            real.get("outside_sales_per_member_eur"),
            get_param("targets.outside_sales_start_eur"),
            f("export_revenue_per_member"),
        ),
        (
            _("Members who could live without a capitalist job"),
            real.get("can_live_without_job_share"),
            get_param("targets.can_live_without_job_year20"),
            f("can_live_without_job"),
        ),
        (
            _("Euro reserve (months of outgoings)"),
            real.get("reserve_months"),
            get_param("tradefund.reserve_target_months"),
            f("reserve_months"),
        ),
    ]
    out = []
    for label, value, target, benchmark in spec:
        v = verdict(value, benchmark)
        out.append(
            {
                "label": label,
                "real": value,
                "target": target,
                "benchmark": benchmark,
                "verdict": v,
                "word": VERDICT_WORDS[v],
            }
        )
    # lower is better for the unsold share and the materials per hour
    for label, value, target, benchmark in (
        (
            _("Products nobody buys (share)"),
            real.get("unsold_share"),
            get_param("targets.unsold_share"),
            f("unsold_share_of_hours"),
        ),
    ):
        ok = value is None or Decimal(str(value)) <= Decimal(str(target))
        v = "unknown" if value is None else "on_track" if ok else "behind"
        out.append(
            {
                "label": label,
                "real": value,
                "target": target,
                "benchmark": benchmark,
                "verdict": v,
                "word": VERDICT_WORDS[v],
            }
        )
    out.append(
        {
            "label": _("Bought materials per hour of work (euros)"),
            "real": real.get("materials_eur_per_hour"),
            "target": get_param("targets.materials_share_of_german"),
            "benchmark": f("euro_inputs_per_member"),
            "verdict": "unknown" if real.get("materials_eur_per_hour") is None else "on_track",
            "word": VERDICT_WORDS["unknown" if real.get("materials_eur_per_hour") is None else "on_track"],
        }
    )
    return out, row, date(int(row["year"]), 1, 1)
