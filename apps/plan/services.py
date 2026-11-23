"""Plan periods, the first plan and proposals (docs/05 section 8). Group, vote and start have their own files."""

from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.rules.services import get_param

from . import calendar, defaults
from .models import PlanPeriod, PlanProposal


class PlanError(ValueError):
    """A plain-words reason why something cannot be done."""


def today() -> date:
    return timezone.localdate()


def period_end(starts_on: date) -> date:
    return date(starts_on.year + int(get_param("plan.period_years")) - 1, 12, 31)


def running_period():
    """The plan that runs now: the latest period with status `running`."""
    return PlanPeriod.objects.filter(status="running").order_by("-starts_on").first()


def running_variant():
    period = running_period()
    return period.adopted_variant if period else None


def next_period(on=None) -> PlanPeriod:
    """The period that the proposals and the group of this season work for (it starts on 1 January)."""
    on = on or today()
    starts = date(calendar.plan_year(on), 1, 1)
    period = PlanPeriod.objects.filter(starts_on=starts).first()
    if period is None:
        period = PlanPeriod.objects.create(starts_on=starts, ends_on=period_end(starts), status="proposals")
    return period


# --- The first plan (P11.T01) ---


def start_first_plan(on=None) -> PlanPeriod:
    """At launch the founders vote yes or no on the default plan of the simulation."""
    from apps.tickets import services as ticket_services
    from apps.votes import services as vote_services

    on = on or today()
    with transaction.atomic():
        if PlanPeriod.objects.exists():
            raise PlanError(_("A plan already exists."))
        period = PlanPeriod.objects.create(starts_on=on, ends_on=period_end(on), status="voting")
        variant = defaults.build_default_variant(period)
        ticket = ticket_services.create_ticket(
            "plan_adoption",
            None,
            _("Adopt the default plan from the simulation?"),
            body=_(
                "The first yearly plan is the default plan: the most successful world of the simulation. "
                "Everything in it can be changed by later plans."
            ),
            action_payload={"period": period.pk, "variant": variant.pk},
            open_now=False,
        )
        ticket.status = "open"
        ticket.save(update_fields=["status"])
        period.referendum = vote_services.schedule_referendum(
            ticket, ticket.title, method="yes_no", days=int(get_param("governance.referendum.days"))
        )
        period.save(update_fields=["referendum"])
        audit.record("system", "plan.first_plan_started", period)
        return period


# --- Proposals (P11.T03) ---


def proposals_open(on=None) -> bool:
    on = on or today()
    return calendar.on("proposals_open", on.year) <= on <= calendar.on("proposals_close", on.year)


def _window_words(on) -> str:
    return _(
        "Plan proposals are collected from %(a)s to %(b)s. For something urgent, ask for a vote of all members."
    ) % {
        "a": calendar.on("proposals_open", on.year).strftime("%-d %B"),
        "b": calendar.on("proposals_close", on.year).strftime("%-d %B"),
    }


KINDS = {k for k, _label in PlanProposal.KINDS}


def quick_check(kind, payload) -> dict:
    """The hours and euros involved, and the plan check. It never refuses (HF-15)."""
    from . import check as plan_check

    eur = Decimal(str(payload.get("eur") or 0))
    hours = Decimal(str(payload.get("hours") or 0))
    request = {
        "type": "plan_proposal",
        "kind": kind,
        **{k: payload[k] for k in ("trade_code", "item", "unit") if payload.get(k)},
    }
    if kind == "invest":
        request["eur_once"] = str(eur)
    elif kind == "budget_change":
        request["eur_monthly"] = str(eur / 12)
    result = plan_check.check(request)
    return {
        "hours": str(hours),
        "eur": str(eur),
        "color": result.color,
        "points": [{"color": p.color, "text": p.text} for p in result.points],
    }


def file_proposal(member, kind, title, brief, payload, on=None) -> PlanProposal:
    """Any verified member files a proposal while the window is open."""
    from apps.members import services as member_services
    from apps.tickets import services as ticket_services

    on = on or today()
    if not member_services.is_verified(member):  # HF-13
        raise PlanError(_("Only verified members can file plan proposals."))
    if kind not in KINDS:
        raise PlanError(_("Please choose what kind of proposal this is."))
    if not proposals_open(on):
        raise PlanError(_window_words(on))
    if not (title or "").strip():
        raise PlanError(_("Please give the proposal a title."))
    payload = dict(payload or {})
    if kind == "parameter_change":
        problems = _parameter_problems(payload)
        if problems:
            raise PlanError(problems)
    with transaction.atomic():
        period = next_period(on)
        ticket = ticket_services.create_ticket("plan_proposal", member, title, body=brief or "", action_payload=payload)
        proposal = PlanProposal.objects.create(
            ticket=ticket, period=period, kind=kind, payload=payload, quick_check=quick_check(kind, payload)
        )
        audit.record(member.number, "plan.proposal_filed", proposal, kind=kind)
        return proposal


def _parameter_problems(payload) -> str:
    from django.core.exceptions import ValidationError

    from apps.rules.models import Parameter
    from apps.rules.services import validate_value

    p = Parameter.objects.filter(key=payload.get("key", "")).first()
    if p is None or p.tier != "plan":
        return _("Only defaults of the plan tier can be changed by the yearly plan.")
    try:
        validate_value(
            key=p.key,
            type=p.type,
            value=payload.get("value"),
            min_value=p.min_value,
            max_value=p.max_value,
            choices=p.choices,
        )
    except ValidationError as e:
        return " ".join(e.messages)
    return ""


def urgent_request(member, title, body):
    """Outside the window: a request for a vote of all members, for urgent matters."""
    from apps.tickets import services as ticket_services

    return ticket_services.create_ticket("referendum_request", member, title, body)


def proposals_by_kind(period):
    rows = {}
    for p in period.proposals.select_related("ticket"):
        rows.setdefault(p.kind, []).append(p)
    return rows


def add_days(d, n):
    return d + timedelta(days=n)
