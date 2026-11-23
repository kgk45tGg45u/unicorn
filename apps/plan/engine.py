"""The engine check of a whole plan (docs/05 section 8, docs/03 section 4): hours, euros, bounds, shares, tax."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.utils.translation import gettext as _

from apps.rules.models import Parameter
from apps.rules.services import get_param, validate_value

from . import defaults

D = Decimal
ONE_MONTH_TREND = D("1.1")  # members' offered hours: the last 3 months' average, and a tenth more


def expected_hours_per_month():
    """The 3-month average of hours paid, a tenth more; None while there is no history."""
    from apps.macro.models import MacroSnapshot

    rows = list(MacroSnapshot.objects.order_by("-period__year", "-period__month")[:3])
    if not rows:
        return None
    return sum((r.hours_paid for r in rows), D(0)) / len(rows) * ONE_MONTH_TREND


def implied_flat_tax(variant) -> Decimal:
    """The flat tax the variant's shares imply: the social and the accumulation share of all hours.

    OWNER-CHECK: with a fixed method it is the fixed rate; otherwise the shares at the start of the plan.
    """
    p = variant.parameters
    method = p.get("economy.flat_tax.method", get_param("economy.flat_tax.method"))
    if method == "fixed":
        return D(str(p.get("economy.flat_tax.fixed_rate", get_param("economy.flat_tax.fixed_rate"))))
    social = D(str(p.get("economy.social_share_start", get_param("economy.social_share_start"))))
    accumulation = D(str(p.get("economy.accumulation_share", get_param("economy.accumulation_share"))))
    low, high = D(str(get_param("economy.flat_tax.min"))), D(str(get_param("economy.flat_tax.max")))
    return min(max(social + accumulation, low), high).quantize(D("0.0001"))


def _bound_issues(variant):
    issues = []
    known = {p.key: p for p in Parameter.objects.filter(key__in=list(variant.parameters))}
    for key, value in sorted(variant.parameters.items()):
        p = known.get(key)
        if p is None or p.tier != "plan":
            issues.append(_("%(key)s is not a default that a yearly plan may set.") % {"key": key})
            continue
        try:
            validate_value(
                key=key, type=p.type, value=value, min_value=p.min_value, max_value=p.max_value, choices=p.choices
            )
        except ValidationError as e:
            issues.append(_("%(key)s: %(why)s") % {"key": key, "why": " ".join(e.messages)})
    return issues


def check_variant(variant) -> dict:
    """The engine's result: plain issues (a variant with issues cannot be submitted) and the numbers behind them."""
    issues = _bound_issues(variant)
    months = len(variant.planned_hours_per_month)
    planned = sum((D(str(h)) for h in variant.planned_hours_per_month), D(0))
    budget_hours = variant.budget_lines.aggregate(t=Sum("hours"))["t"] or D(0)
    invest_hours = variant.investments.aggregate(t=Sum("hours"))["t"] or D(0)
    if budget_hours + invest_hours > planned and (budget_hours + invest_hours) > 0:
        issues.append(
            _("The plan uses %(used)s hours but only %(planned)s hours are planned.")
            % {"used": (budget_hours + invest_hours).quantize(D("1")), "planned": planned.quantize(D("1"))}
        )
    trend = expected_hours_per_month()
    if trend is not None and months and planned > trend * months * D("1.5"):
        issues.append(
            _("The plan expects %(planned)s hours, far above what members offer now (about %(trend)s a year).")
            % {"planned": planned.quantize(D("1")), "trend": (trend * months).quantize(D("1"))}
        )
    euros_out = (variant.budget_lines.aggregate(t=Sum("eur"))["t"] or D(0)) + (
        variant.investments.aggregate(t=Sum("eur"))["t"] or D(0)
    )
    euros_in = sum((D(str(e)) for e in variant.expected_euros_in_per_month), D(0))
    inflow = defaults.trailing_euro_inflow()
    if euros_out > euros_in:
        issues.append(
            _("The plan spends %(out)s euros but expects only %(in_)s euros to come in.")
            % {"out": euros_out.quantize(D("1")), "in_": euros_in.quantize(D("1"))}
        )
    if inflow > 0 and euros_in > inflow * 2:
        issues.append(
            _("The plan expects %(in_)s euros, more than twice what came in during the last 12 months (%(past)s).")
            % {"in_": euros_in.quantize(D("1")), "past": inflow.quantize(D("1"))}
        )
    p = variant.parameters
    start = D(str(p.get("economy.social_share_start", get_param("economy.social_share_start"))))
    end = D(str(p.get("economy.social_share_end", get_param("economy.social_share_end"))))
    if start > end:
        issues.append(_("The social share cannot shrink: its start is above its end."))
    tax = implied_flat_tax(variant)
    result = {
        "issues": [str(i) for i in issues],
        "implied_tax": str(tax),
        "hours": {"planned": str(planned), "used": str(budget_hours + invest_hours)},
        "euros": {"in": str(euros_in), "out": str(euros_out), "past_year_in": str(inflow)},
    }
    variant.engine_check = result
    variant.save(update_fields=["engine_check"])
    return result
