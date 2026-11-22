"""The secretariat: sends each ticket to the right deciders (docs/05 section 2). It proposes; people decide (HF-15)."""

from django.db import transaction

from apps.core import audit

from . import types

# type -> function(ticket) -> bool: True when the automatic rule is satisfied. P08 adds "purchase".
AUTO_RULES: dict = {}


def _auto_open_unit(ticket) -> bool:
    return (ticket.plan_check or {}).get("color") == "green"


AUTO_RULES["open_unit"] = _auto_open_unit

# ticket type -> the kind of council decision that carries it
COUNCIL_KINDS = {"close_unit": "other", "join_forces": "other", "council_decision": "other"}


def route(ticket):
    """Set the decision method from the type, then start deciding by scope and method."""
    from . import confirm

    info = types.TYPES[ticket.type]
    with transaction.atomic():
        ticket.decision_method = info.method
        ticket.save(update_fields=["decision_method"])
        method = info.method
        if method == "council" and ticket.scope == "unit" and ticket.scope_unit_id:
            _start_council(ticket)
        elif method == "confirmers":
            confirm.start_confirmers(ticket)
        elif method == "panel":
            confirm.start_panel(ticket)
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
