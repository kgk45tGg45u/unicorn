"""What the app does when a ticket is approved or finally rejected (docs/05 section 5 item 1).

An action runs inside the same database transaction that records the approval, and its result is written on the
ticket. If it fails, the ticket becomes `in_action` with the error in plain words, and the operators are told.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from django.db import transaction
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.notify import notify

from . import services as ticket_services
from . import types
from .models import Ticket


@dataclass
class Action:
    execute: Callable  # execute(ticket) -> dict (stored in ticket.action_result)
    validate: Callable = field(default=lambda payload: [])  # validate(payload) -> list of plain-words problems
    finishes: bool = True  # False: the ticket stays `in_action` until something else (a mandate, tasks) is done


ACTIONS: dict[str, Action] = {}


def register(name, execute, validate=None, finishes=True):
    ACTIONS[name] = Action(execute=execute, validate=validate or (lambda payload: []), finishes=finishes)


def problems(action_name, payload) -> list[str]:
    action = ACTIONS.get(action_name)
    return action.validate(payload or {}) if action else []


def _tell_operators(ticket, text):
    from apps.members.models import Member

    for m in Member.objects.filter(user__is_staff=True, deleted=False):
        notify(m, text, f"/tickets/{ticket.number}/")


def approve(ticket, how=""):
    """Record the approval and run the action. Safe to call twice: an approved ticket is left alone."""
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
        if ticket.status in ("approved", "done", "in_action", "withdrawn"):
            return ticket
        ticket_services.set_status(ticket, "approved", "")
        audit.record("system", "ticket.approved", ticket, how=how)
        action = ACTIONS.get(ticket.action) if ticket.action else None
        if not ticket.action:
            return ticket
        if action is None:
            # The part of the app that carries this out is not built yet; the approval stays on record.
            ticket.action_result = {"pending": str(_("Nothing carries this out yet."))}
            ticket.save(update_fields=["action_result"])
            return ticket
        try:
            with transaction.atomic():
                result = action.execute(ticket)
        except Exception as e:  # noqa: BLE001  any failure must leave the ticket in a readable state
            message = str(e) if isinstance(e, ValueError) else _("Something went wrong while carrying this out.")
            audit.record("system", "ticket.action_failed", ticket, action=ticket.action, error=repr(e)[:200])
            ticket.action_result = {"error": str(message)}
            ticket_services.set_status(ticket, "in_action", str(message))
            ticket.save(update_fields=["action_result"])
            _tell_operators(
                ticket, _("%(number)s was approved but could not be carried out.") % {"number": ticket.number}
            )
            return ticket
        ticket.action_result = result or {}
        ticket.save(update_fields=["action_result"])
        ticket_services.set_status(ticket, "done" if action.finishes else "in_action", "")
        audit.record("system", "ticket.action_done", ticket, action=ticket.action)
        return ticket


def reject(ticket):
    """Run what the type does when the ticket is finally rejected (for example: a flag is kept)."""
    info = types.TYPES.get(ticket.type)
    name = info.reject_action if info else None
    action = ACTIONS.get(name) if name else None
    if action is None:
        return ticket
    with transaction.atomic():
        result = action.execute(ticket)
        ticket.action_result = result or {}
        ticket.save(update_fields=["action_result"])
        audit.record("system", "ticket.reject_action_done", ticket, action=name)
    return ticket
