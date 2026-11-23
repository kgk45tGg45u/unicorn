"""The secretariat: sends each ticket to the right deciders (docs/05 section 2). It proposes; people decide (HF-15)."""

from django.db import transaction
from django.utils.translation import gettext_lazy as _t

from apps.core import audit

from . import types

# type -> function(ticket) -> bool: True when the automatic rule is satisfied. The trade fund adds "purchase".
AUTO_RULES: dict = {}


def _auto_open_unit(ticket) -> bool:
    return (ticket.plan_check or {}).get("color") == "green"


AUTO_RULES["open_unit"] = _auto_open_unit

# Functions called with (ticket) when a ticket is routed, before it is sent to its deciders. They may notify people
# (a union asked to advise) but must never change the ticket's method (HF-15).
ROUTE_HOOKS: list = []

# type -> function(ticket) -> bool: True when the app routed the ticket itself (P08 adds "purchase" for big amounts).
CUSTOM_ROUTES: dict = {}

# ticket type -> the kind of council decision that carries it
COUNCIL_KINDS = {
    "close_unit": "other",
    "join_forces": "other",
    "council_decision": "other",
    "union_join": "other",
    "union_leave": "other",
}


def route(ticket):
    """Set the decision method from the type, then start deciding by scope and method."""
    from . import confirm

    info = types.TYPES[ticket.type]
    with transaction.atomic():
        ticket.decision_method = info.method
        ticket.save(update_fields=["decision_method"])
        method = info.method
        for hook in ROUTE_HOOKS:
            hook(ticket)
        if ticket.type == "parameter_change":
            return _route_parameter(ticket)
        custom = CUSTOM_ROUTES.get(ticket.type)
        if custom is not None and custom(ticket):
            return ticket
        if method == "council" and ticket.scope == "unit" and ticket.scope_unit_id:
            _start_council(ticket)
        elif method == "confirmers":
            confirm.start_confirmers(ticket)
        elif method == "panel":
            confirm.start_panel(ticket)
        elif method == "referendum":
            from apps.votes import services as vote_services

            vote_services.schedule_referendum(ticket, ticket.title)
        elif method == "mediation":
            from . import mediation

            mediation.start(ticket)
        elif method == "auto":
            rule = AUTO_RULES.get(ticket.type)
            if rule is not None and rule(ticket):
                from . import actions

                audit.record("system", "ticket.auto_approved", ticket)
                actions.approve(ticket, how="auto")
            else:
                ticket.decision_method = "confirmers"
                ticket.save(update_fields=["decision_method"])
                confirm.start_confirmers(ticket)
        # "none", "plan", "referendum", "mediation": the ticket stays open; other parts of the app pick it up.
    return ticket


def _start_council(ticket):
    """A decision of the unit's own council. Its tally later approves or rejects the ticket."""
    payload = ticket.action_payload or {}
    if payload.get("council_decision"):
        return
    from apps.units import services as unit_services

    decision = unit_services.open_system_decision(
        ticket.scope_unit,
        f"{ticket.number} {ticket.title}"[:120],
        ticket.body_md or ticket.brief_md,
        kind=COUNCIL_KINDS.get(ticket.type, "other"),
        payload={"ticket": ticket.number},
    )
    ticket.action_payload = {**payload, "council_decision": decision.pk}
    ticket.save(update_fields=["action_payload"])
    audit.record("system", "ticket.council_started", ticket, decision=decision.pk)


def suggest_answerers(ticket) -> list:
    """Members who might know. Empty until reputation exists (P13)."""
    return []


PLAN_WORDS = _t(
    "This is decided in the yearly plan (docs/05 section 8), or by a referendum. "
    "You can turn it into a request for a vote of all members, or into a proposal for the yearly plan."
)
HARD_WORDS = _t("This needs a hard-frame change. See the procedure for changing the hard frame.")


def _route_parameter(ticket):
    """HF-16: a default changes only at its tier. Confirm tier: confirmers. Referendum tier: a completeness check
    by confirmers, then a vote of all. Plan tier: the yearly plan or a referendum. Hard tier: the hard-frame change."""
    from apps.rules.models import Parameter

    from . import confirm
    from . import services as ticket_services

    tier = Parameter.objects.get(key=ticket.action_payload["key"]).tier
    if tier == "hard":
        ticket.decision_method = "none"
        ticket.save(update_fields=["decision_method"])
        ticket_services.set_status(ticket, "rejected", str(HARD_WORDS))
    elif tier == "plan":
        ticket.decision_method = "plan"
        ticket.save(update_fields=["decision_method"])
        ticket_services.set_status(ticket, "rejected", str(PLAN_WORDS))
    else:
        if tier == "referendum":
            ticket.action_payload = {**ticket.action_payload, "then": "referendum"}
            ticket.save(update_fields=["action_payload"])
        confirm.start_confirmers(ticket)
    return ticket
