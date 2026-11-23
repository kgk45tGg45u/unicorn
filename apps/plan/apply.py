"""Adopting a plan and putting it to work (docs/05 section 8): parameters, hours, investments, focus, closures."""

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.notify import notify
from apps.rules.services import get_param, set_param

from . import services
from .models import PlanPeriod, PlanVariant

HEARING_DAYS = 30


# --- Adoption (P11.T01, T06) ---


def _winner(period, referendum) -> PlanVariant | None:
    if referendum.method == "yes_no":
        return period.variants.filter(is_default=True).first()
    return period.variants.filter(name=(referendum.result or {}).get("winner")).first()


def adopt_plan(ticket):
    """The ticket's action: the winning variant becomes the period's plan, and starts at once if its day has come."""
    from apps.votes.models import Referendum

    period = PlanPeriod.objects.select_for_update().get(pk=ticket.action_payload["period"])
    referendum = Referendum.objects.filter(ticket=ticket).order_by("-id").first()
    variant = _winner(period, referendum)
    if variant is None:
        raise ValueError(_("The vote did not name a plan."))
    period.adopted_variant, period.referendum, period.status = variant, referendum, "adopted"
    period.save(update_fields=["adopted_variant", "referendum", "status"])
    audit.record("system", "plan.adopted", period, variant=variant.name, ticket=ticket.number)
    if period.starts_on <= services.today():
        apply_plan(period)
    return {"period": period.pk, "variant": variant.name}


def plan_vote_failed(ticket):
    """Too few voted: the current plan runs on, and the vote is repeated after `quorum_fail_extension_months`."""
    from apps.members.services import _add_months

    period = PlanPeriod.objects.filter(pk=ticket.action_payload.get("period")).first()
    if period is None:
        return {}
    months = int(get_param("plan.quorum_fail_extension_months"))
    again = _add_months(timezone.now(), months).date()
    period.revote_on, period.extended_until = again, again
    period.save(update_fields=["revote_on", "extended_until"])
    audit.record("system", "plan.vote_failed", period, revote_on=str(again))
    return {"revote_on": str(again)}


def repeat_vote(on=None) -> int:
    """Daily: open the repeated vote when its day has come."""
    from . import vote

    on = on or services.today()
    done = 0
    for period in PlanPeriod.objects.filter(revote_on__isnull=False, revote_on__lte=on, status="voting"):
        period.revote_on = None
        period.save(update_fields=["revote_on"])
        vote.start_vote(period)
        done += 1
    return done


# --- Applying a plan (P11.T07) ---


def apply_plan(period, on=None) -> PlanPeriod:
    """On the period's first day: parameters at the plan tier, planned hours per month, investments, status running."""
    from apps.ledger.models import Period as LedgerPeriod
    from apps.ledger.services import current_period

    variant = period.adopted_variant
    if variant is None or period.status == "running":
        return period
    ticket_number = _ticket_number(period)
    year = period.starts_on.year
    with transaction.atomic():
        for key, value in sorted(variant.parameters.items()):
            from apps.rules.models import Parameter

            if Parameter.objects.get(key=key).value != value:
                set_param(key, value, decided_by=ticket_number, decided_tier="plan", reason=f"Yearly plan {year}")
        for i, hours in enumerate(variant.planned_hours_per_month):
            month_index = period.starts_on.month - 1 + i
            y, m = period.starts_on.year + month_index // 12, month_index % 12 + 1
            if (y, m) == (timezone.localdate().year, timezone.localdate().month):
                row = current_period()
            else:
                row = LedgerPeriod.objects.filter(year=y, month=m).first()
                if row is None:
                    continue  # made later by `current_period`, which reads the plan's hours
            row.planned_hours = Decimal(str(hours))
            row.save(update_fields=["planned_hours"])
        PlanPeriod.objects.filter(status="running").exclude(pk=period.pk).update(status="closed")
        period.status = "running"
        period.save(update_fields=["status"])
        carry_out_investments(variant)
        audit.record("system", "plan.started", period, variant=variant.name)
    return period


def _ticket_number(period) -> str:
    return period.referendum.ticket.number if period.referendum_id else "plan"


def start_due_periods(on=None) -> int:
    """Daily: adopted plans start on their first day."""
    on = on or services.today()
    done = 0
    for period in PlanPeriod.objects.filter(status="adopted", starts_on__lte=on):
        apply_plan(period, on)
        done += 1
    return done


def planned_hours_for(year, month):
    """The planned hours of a month from the running plan, or None."""
    period = services.running_period()
    if period is None or period.adopted_variant is None:
        return None
    index = (year - period.starts_on.year) * 12 + month - period.starts_on.month
    hours = period.adopted_variant.planned_hours_per_month
    return Decimal(str(hours[index])) if 0 <= index < len(hours) else None


def carry_out_investments(variant) -> int:
    """Investments with a unit become purchase requests, in priority order; the allocation order funds them."""
    from apps.tradefund import purchases
    from apps.units import services as unit_services

    done = 0
    for item in variant.investments.filter(carried_out_at__isnull=True).select_related("unit", "item"):
        worker = unit_services.workers(item.unit).first() if item.unit_id else None
        if worker is None:
            continue  # OWNER-CHECK: an investment with no unit waits until a unit asks for it
        purchases.create_purchase(
            worker.member,
            item.title,
            item.eur,
            unit=item.unit,
            item=item.item,
            why=_("Part of the yearly plan"),
            source="tool",
        )
        item.carried_out_at = timezone.now()
        item.save(update_fields=["carried_out_at"])
        done += 1
    return done


# --- Focus and closures ---


def focus_items():
    variant = services.running_variant()
    return list(variant.focus_items.select_related("item")) if variant else []


def _units_of(closure):
    from apps.units.models import Unit

    qs = Unit.objects.exclude(status__in=("closed", "merged"))
    if closure.unit_id:
        return qs.filter(pk=closure.unit_id)
    if closure.trade_code:
        return qs.filter(trade_code=closure.trade_code)
    if closure.item_id:
        return qs.filter(offers__item=closure.item).distinct()
    return qs.none()


def run_closures(on=None) -> int:
    """Daily: open the hearing 30 days before; on the closing day, the units finish their orders and offers retire."""
    from apps.catalogue.models import Offer
    from apps.tickets import services as ticket_services
    from apps.units import services as unit_services

    on = on or services.today()
    variant = services.running_variant()
    if variant is None:
        return 0
    done = 0
    for closure in variant.closures.filter(closed_at__isnull=True):
        units = list(_units_of(closure))
        if closure.hearing_opened_at is None and on >= closure.hearing_until - timedelta(days=HEARING_DAYS):
            for unit in units:
                ticket = ticket_services.create_ticket(
                    "plan_hearing",
                    None,
                    _("The yearly plan closes %(what)s: hearing of %(unit)s")
                    % {
                        "what": closure.trade_code or (closure.item.name if closure.item_id else unit.name),
                        "unit": unit.name,
                    },
                    body=_("The plan closes this from %(date)s. The council can say what it thinks until %(until)s.")
                    % {"date": closure.from_date, "until": closure.hearing_until},
                    scope="unit",
                    scope_unit=unit,
                )
                for w in unit_services.workers(unit):
                    notify(
                        w.member,
                        _("The yearly plan closes your unit from %(date)s. Please read and comment.")
                        % {"date": closure.from_date},
                        f"/tickets/{ticket.number}/",
                    )
            closure.hearing_opened_at = timezone.now()
            closure.save(update_fields=["hearing_opened_at"])
            done += 1
        if on >= closure.from_date and on >= closure.hearing_until:
            for unit in units:
                Offer.objects.filter(unit=unit, status__in=("active", "paused")).update(status="retired")
                if unit.status not in ("closing", "closed"):
                    unit.status = "closing"  # its open orders are finished first
                    unit.save(update_fields=["status"])
                    audit.record("system", "unit.closing", unit, reason="yearly plan closure")
            if closure.item_id:
                Offer.objects.filter(item=closure.item, status__in=("active", "paused")).update(status="retired")
            closure.closed_at = timezone.now()
            closure.save(update_fields=["closed_at"])
            done += 1
    return done


def finish_closing_units() -> int:
    """Daily: a unit the plan closes becomes `closed` once nothing blocks it any more."""
    from apps.units import services as unit_services
    from apps.units.models import Unit

    done = 0
    for unit in Unit.objects.filter(status="closing"):
        if unit_services.CLOSE_CHECKS and any(c(unit) for c in unit_services.CLOSE_CHECKS):
            continue
        unit.status, unit.closed_at = "closed", timezone.now()
        unit.save(update_fields=["status", "closed_at"])
        audit.record("system", "unit.closed", unit, reason="yearly plan closure")
        done += 1
    return done


# --- Emergency changes ---


def red_months() -> int:
    """How many of the latest monthly closes in a row had a red light."""
    from apps.macro.models import MacroSnapshot

    count = 0
    for snap in MacroSnapshot.objects.order_by("-period__year", "-period__month")[:24]:
        if any(light.get("color") == "red" for light in (snap.lights or {}).values()):
            count += 1
        else:
            break
    return count


def propose_emergency(member, changes: dict, reason: str):
    """A member of the planning group may propose an emergency change after a long red light; confirmers decide."""
    from apps.rules.models import Parameter
    from apps.tickets import services as ticket_services

    from .models import GroupSeat

    needed = int(get_param("plan.emergency_red_months"))
    if red_months() < needed:
        raise services.PlanError(
            _("An emergency change needs a red warning light for %(n)s months in a row.") % {"n": needed}
        )
    if not GroupSeat.objects.filter(member=member, group__period__status="running", replaced=False).exists():
        raise services.PlanError(_("Only members of the planning group can propose an emergency change."))
    if not changes or not (reason or "").strip():
        raise services.PlanError(_("Please say what changes and why."))
    for key in changes:
        p = Parameter.objects.filter(key=key).first()
        if p is None or p.tier != "plan":
            raise services.PlanError(_("An emergency change can only touch defaults of the plan tier."))
    return ticket_services.create_ticket(
        "plan_emergency",
        member,
        _("Emergency change of the plan"),
        body=reason,
        action_payload={"changes": changes, "reason": reason},
    )


def apply_emergency(ticket):
    changes = ticket.action_payload["changes"]
    for key, value in changes.items():
        set_param(
            key,
            value,
            decided_by=ticket.number,
            decided_tier="plan",
            reason=ticket.action_payload.get("reason") or "Emergency change",
        )
    return {"changed": sorted(changes)}


def register():
    from apps.tickets import actions

    actions.register("adopt_plan", adopt_plan)
    actions.register("plan_vote_failed", plan_vote_failed)
    actions.register("apply_emergency", apply_emergency)
