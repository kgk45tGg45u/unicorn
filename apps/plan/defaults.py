"""The default plan: the current `plan`-tier defaults and the last twelve months as budget (docs/05 section 8)."""

from datetime import date
from decimal import Decimal

from django.db.models import Sum

from apps.rules.models import Parameter

from .models import CATEGORIES, BudgetLine, PlanVariant


def plan_parameters() -> dict:
    return {p.key: p.value for p in Parameter.objects.filter(tier="plan").order_by("key")}


def _trailing_hours(field) -> Decimal:
    from apps.macro.models import MacroSnapshot

    rows = MacroSnapshot.objects.order_by("-period__year", "-period__month")[:12]
    return sum((getattr(r, field) for r in rows), Decimal(0))


def months_between(starts_on: date, ends_on: date) -> int:
    return (ends_on.year - starts_on.year) * 12 + ends_on.month - starts_on.month + 1


def _planned_hours(months) -> list:
    """Each month: the average of the last three months' paid hours, or zero before there is any data."""
    from apps.macro.models import MacroSnapshot

    rows = list(MacroSnapshot.objects.order_by("-period__year", "-period__month")[:3])
    average = sum((r.hours_paid for r in rows), Decimal(0)) / len(rows) if rows else Decimal(0)
    return [str(average.quantize(Decimal("0.01")))] * months


def build_default_variant(period, name="Default plan") -> PlanVariant:
    """Copy the current plan-tier defaults. Budget lines come from the trailing 12 months, or are zero at launch."""
    months = months_between(period.starts_on, period.ends_on)
    variant = PlanVariant.objects.create(
        period=period,
        name=name,
        summary_md="The default plan: today's defaults, and the last twelve months as the budget.",
        parameters=plan_parameters(),
        planned_hours_per_month=_planned_hours(months),
        expected_euros_in_per_month=[str(Decimal(0))] * months,
        is_default=True,
    )
    social, accumulation = _trailing_hours("social"), _trailing_hours("accumulation")
    # OWNER-CHECK: euro lines start at zero; only the hours of social work and tools are taken from the books.
    hours = {"social_security": social, "tools": accumulation}
    for key, _label in CATEGORIES:
        BudgetLine.objects.create(
            variant=variant, category=key, hours=hours.get(key, Decimal(0)).quantize(Decimal("0.01"))
        )
    return variant


def trailing_euro_inflow() -> Decimal:
    """What came into the fund in the last 12 months as set-asides and donations, in euros."""
    from django.utils import timezone

    from apps.tradefund import fx
    from apps.tradefund.models import FundEntry

    since = timezone.now().replace(year=timezone.now().year - 1)
    rows = (
        FundEntry.objects.filter(kind__in=("setaside", "donation"), amount__gt=0, created_at__gte=since)
        .values_list("currency")
        .annotate(t=Sum("amount"))
    )
    return sum((fx.to_eur(t, c) for c, t in rows), Decimal(0))
