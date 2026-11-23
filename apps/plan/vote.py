"""Comments and the ranked vote (docs/05 section 8, P11.T06)."""

from decimal import Decimal

from django.db import transaction
from django.utils.translation import gettext as _

from apps.core import audit
from apps.rules.services import get_param

from . import calendar, engine, services
from .models import PlanComment


def comment(variant, member, body):
    from apps.members import services as member_services

    if not member_services.is_verified(member):  # HF-13
        raise services.PlanError(_("Only verified members can comment on a plan."))
    if variant.period.status != "comments" and not (variant.period.status == "drafting" and variant.submitted):
        raise services.PlanError(_("This plan is not open for comments."))
    if not (body or "").strip():
        raise services.PlanError(_("Please write a comment."))
    return PlanComment.objects.create(variant=variant, member=member, body=body.strip())


def differences(variant) -> list[str]:
    """What changes against the plan that runs now (or against today's defaults)."""
    from apps.rules.models import Parameter

    current = {p.key: p.value for p in Parameter.objects.filter(key__in=list(variant.parameters))}
    return [
        _("%(key)s: %(old)s becomes %(new)s") % {"key": k, "old": current.get(k), "new": v}
        for k, v in sorted(variant.parameters.items())
        if current.get(k) != v
    ]


def brief_for(variant) -> str:
    result = variant.engine_check or engine.check_variant(variant)
    lines = [
        f"## {variant.name}",
        variant.summary_md.strip(),
        _("Implied flat tax: %(tax)s%%") % {"tax": (Decimal(result["implied_tax"]) * 100).quantize(Decimal("0.1"))},
    ]
    top = variant.budget_lines.order_by("-eur", "-hours")[:5]
    lines.append(_("Main budget lines:"))
    lines.extend(f"- {line.get_category_display()} {line.trade_code}: {line.hours} h, {line.eur} €" for line in top)
    lines.append(
        _("Investments: %(i)s, focus: %(f)s, closures: %(c)s")
        % {"i": variant.investments.count(), "f": variant.focus_items.count(), "c": variant.closures.count()}
    )
    lines.append(
        _("Forecast: %(f)s")
        % {"f": variant.forecast.note or _("attached") if variant.forecast_id else _("no forecast")}
    )
    diffs = differences(variant)
    lines.append(_("Differences from today's defaults:") + (" " + "; ".join(diffs) if diffs else " " + _("none")))
    return "\n".join(line for line in lines if line)


def start_vote(period, on=None):
    """On `vote_open`: a ranked vote of all members (instant runoff) on the submitted variants."""
    from apps.tickets import services as ticket_services
    from apps.votes import services as vote_services

    on = on or services.today()
    variants = list(period.variants.filter(submitted=True))
    if not variants:
        # the vote is repeated with the same plans after a failed quorum
        raise services.PlanError(_("There are no plans to vote on."))
    with transaction.atomic():
        year = period.starts_on.year
        ticket = ticket_services.create_ticket(
            "plan_adoption",
            None,
            _("Choose the yearly plan for %(year)s") % {"year": year},
            body=_("Rank the plans. The plan that wins takes effect on %(day)s.") % {"day": period.starts_on},
            brief="\n\n".join(brief_for(v) for v in variants),
            action_payload={"period": period.pk},
            open_now=False,
        )
        days = max((calendar.on("vote_close", on.year) - calendar.on("vote_open", on.year)).days + 1, 1)
        referendum = vote_services.schedule_referendum(
            ticket,
            ticket.title,
            method=get_param("plan.vote_method"),
            options=[v.name for v in variants],
            days=days,
            quorum=get_param("governance.referendum.quorum"),
        )
        period.status, period.referendum = "voting", referendum
        period.save(update_fields=["status", "referendum"])
        audit.record("system", "plan.vote_scheduled", period, variants=len(variants))
        return referendum
