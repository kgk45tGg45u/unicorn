"""The group's workspace: whole plans as variants, checked by the engine (docs/05 section 8, P11.T05)."""

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.core import audit
from apps.rules.models import Parameter
from apps.rules.services import get_param, validate_value

from . import engine, services
from . import group as group_module
from .models import BudgetLine, ClosureItem, FocusItem, InvestmentItem, PlanVariant


def _need_seat(member, variant):
    group = variant.period.groups.filter(kind="yearly").first()
    if group is None or not group_module.is_seat(member, group):
        raise services.PlanError(_("Only members of the planning group can change the plans."))


def create_variant(member, period, name, copy_from=None) -> PlanVariant:
    """A new variant starts from the default plan (or a copy of another variant)."""
    source = copy_from or period.variants.filter(is_default=True).first()
    group = period.groups.filter(kind="yearly").first()
    if group is None or not group_module.is_seat(member, group):
        raise services.PlanError(_("Only members of the planning group can change the plans."))
    if not (name or "").strip():
        raise services.PlanError(_("Please name the plan."))
    if period.variants.filter(name=name.strip()).exists():
        raise services.PlanError(_("A plan with this name exists already."))
    with transaction.atomic():
        v = PlanVariant.objects.create(
            period=period,
            name=name.strip()[:60],
            summary_md=source.summary_md if source else "",
            parameters=dict(source.parameters) if source else {},
            planned_hours_per_month=list(source.planned_hours_per_month) if source else [],
            expected_euros_in_per_month=list(source.expected_euros_in_per_month) if source else [],
        )
        if source:
            for model, fields in (
                (BudgetLine, ("category", "trade_code", "hours", "eur")),
                (
                    InvestmentItem,
                    ("title", "item", "trade_code", "unit", "eur", "hours", "priority", "as_project_unit"),
                ),
                (FocusItem, ("item", "trade_code", "text")),
                (ClosureItem, ("item", "trade_code", "unit", "from_date", "hearing_until")),
            ):
                for row in model.objects.filter(variant=source):
                    model.objects.create(variant=v, **{f: getattr(row, f) for f in fields})
        audit.record(member.number, "plan.variant_created", v)
        return v


def copy_variant(member, variant, name):
    return create_variant(member, variant.period, name, copy_from=variant)


def _editable(variant, member):
    _need_seat(member, variant)
    if variant.submitted:
        raise services.PlanError(_("This plan is already submitted."))


def set_parameter(member, variant, key, value):
    """Only `plan`-tier keys, within their bounds (HF-16)."""
    _editable(variant, member)
    p = Parameter.objects.filter(key=key).first()
    if p is None or p.tier != "plan":
        raise services.PlanError(_("A yearly plan can only set defaults of the plan tier."))
    try:
        value = validate_value(
            key=key, type=p.type, value=value, min_value=p.min_value, max_value=p.max_value, choices=p.choices
        )
    except ValidationError as e:
        raise services.PlanError(" ".join(e.messages)) from None
    variant.parameters = {**variant.parameters, key: value if not isinstance(value, Decimal) else float(value)}
    variant.save(update_fields=["parameters"])
    return variant


def set_budget_line(member, variant, category, hours=0, eur=0, trade_code=""):
    _editable(variant, member)
    try:
        hours, eur = Decimal(str(hours)), Decimal(str(eur))
    except InvalidOperation:
        raise services.PlanError(_("Please enter numbers.")) from None
    if hours < 0 or eur < 0:
        raise services.PlanError(_("Budget lines cannot be negative."))
    line, _created = BudgetLine.objects.update_or_create(
        variant=variant, category=category, trade_code=trade_code, defaults={"hours": hours, "eur": eur}
    )
    return line


def set_months(member, variant, hours_per_month, euros_in_per_month):
    _editable(variant, member)
    variant.planned_hours_per_month = [str(Decimal(str(h))) for h in hours_per_month]
    variant.expected_euros_in_per_month = [str(Decimal(str(e))) for e in euros_in_per_month]
    variant.save(update_fields=["planned_hours_per_month", "expected_euros_in_per_month"])
    return variant


def add_investment(member, variant, title, eur=0, hours=0, unit=None, item=None, trade_code="", priority=100):
    _editable(variant, member)
    return InvestmentItem.objects.create(
        variant=variant,
        title=title,
        eur=Decimal(str(eur)),
        hours=Decimal(str(hours)),
        unit=unit,
        item=item,
        trade_code=trade_code,
        priority=priority,
    )


def add_focus(member, variant, text, item=None, trade_code=""):
    _editable(variant, member)
    return FocusItem.objects.create(variant=variant, text=text, item=item, trade_code=trade_code)


def add_closure(member, variant, from_date, hearing_until, item=None, trade_code="", unit=None):
    _editable(variant, member)
    if hearing_until >= from_date:
        raise services.PlanError(_("The hearing must end before the closing day."))
    return ClosureItem.objects.create(
        variant=variant, from_date=from_date, hearing_until=hearing_until, item=item, trade_code=trade_code, unit=unit
    )


def compare(a: PlanVariant, b: PlanVariant) -> dict:
    keys = sorted(set(a.parameters) | set(b.parameters))
    return {
        "parameters": [
            (k, a.parameters.get(k), b.parameters.get(k)) for k in keys if a.parameters.get(k) != b.parameters.get(k)
        ],
        "implied_tax": (engine.implied_flat_tax(a), engine.implied_flat_tax(b)),
        "counts": {
            n: (getattr(a, n).count(), getattr(b, n).count()) for n in ("investments", "focus_items", "closures")
        },
    }


def mark_submitted(variant):
    result = engine.check_variant(variant)
    if result["issues"]:
        raise services.PlanError(" ".join(result["issues"]))
    variant.submitted = True
    variant.save(update_fields=["submitted"])
    return variant


def submit_variant(member, variant):
    """A variant with issues cannot be submitted."""
    _need_seat(member, variant)
    return mark_submitted(variant)


def leave_out(member, proposal, reason):
    group = proposal.period.groups.filter(kind="yearly").first()
    if group is None or not group_module.is_seat(member, group):
        raise services.PlanError(_("Only members of the planning group can decide this."))
    if not (reason or "").strip():
        raise services.PlanError(_("Please say why the proposal is left out."))
    proposal.status, proposal.left_out_reason = "left_out", reason.strip()[:300]
    proposal.save(update_fields=["status", "left_out_reason"])
    return proposal


def finish_drafting(period) -> list:
    """At `drafting_close`: 2 to 3 whole plans must be submitted; proposals left out get a reason."""
    submitted = list(period.variants.filter(submitted=True))
    low, high = int(get_param("plan.variants_min")), int(get_param("plan.variants_max"))
    if not low <= len(submitted) <= high:
        raise services.PlanError(
            _("The group must submit between %(a)s and %(b)s whole plans; it has %(n)s.")
            % {"a": low, "b": high, "n": len(submitted)}
        )
    with transaction.atomic():
        for proposal in period.proposals.filter(status="open"):
            proposal.status = "left_out"
            proposal.left_out_reason = _("The planning group did not include it in a plan.")
            proposal.save(update_fields=["status", "left_out_reason"])
        period.status = "comments"
        period.save(update_fields=["status"])
        audit.record("system", "plan.drafting_closed", period, variants=len(submitted))
    return submitted


# --- Putting proposals into a variant ---


def _put(variant, proposal):
    """Turn a proposal's payload into the matching plan item of the variant."""
    from datetime import timedelta

    p, kind = proposal.payload, proposal.kind
    if kind == "invest":
        InvestmentItem.objects.create(
            variant=variant,
            title=proposal.ticket.title,
            trade_code=p.get("trade_code", ""),
            eur=Decimal(str(p.get("eur") or 0)),
            hours=Decimal(str(p.get("hours") or 0)),
        )
    elif kind == "focus":
        FocusItem.objects.create(variant=variant, trade_code=p.get("trade_code", ""), text=proposal.ticket.title)
    elif kind == "close":
        start = variant.period.starts_on
        ClosureItem.objects.create(
            variant=variant,
            trade_code=p.get("trade_code", ""),
            from_date=start + timedelta(days=31),
            hearing_until=start,
        )
    elif kind in ("share_change", "parameter_change"):
        param = Parameter.objects.get(key=p["key"])
        value = validate_value(
            key=param.key,
            type=param.type,
            value=p["value"],
            min_value=param.min_value,
            max_value=param.max_value,
            choices=param.choices,
        )
        variant.parameters = {**variant.parameters, param.key: float(value) if isinstance(value, Decimal) else value}
        variant.save(update_fields=["parameters"])
    elif kind == "budget_change":
        BudgetLine.objects.update_or_create(
            variant=variant,
            category=p.get("category", "tools"),
            trade_code=p.get("trade_code", ""),
            defaults={"hours": Decimal(str(p.get("hours") or 0)), "eur": Decimal(str(p.get("eur") or 0))},
        )


def include_proposal(variant, proposal):
    """The group decided that the proposal goes into this variant."""
    with transaction.atomic():
        variant.proposals.add(proposal)
        _put(variant, proposal)
        proposal.status = "included"
        proposal.save(update_fields=["status"])
    return variant
