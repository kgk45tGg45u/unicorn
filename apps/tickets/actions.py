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


# --- The actions (P06.T07) ---


def _need(*keys):
    def validate(payload):
        return [] if all(payload.get(k) for k in keys) else [_("This ticket does not say what it is about.")]

    return validate


def _unit_of(ticket):
    from apps.units.models import Unit

    return Unit.objects.get(pk=ticket.action_payload["unit_id"])


def _open_unit(ticket):
    from apps.units import services as unit_services

    unit = unit_services.release_unit(_unit_of(ticket))
    return {"unit": unit.slug, "status": unit.status}


def _close_unit(ticket):
    from apps.units import services as unit_services

    reason = ticket.action_payload.get("reason") or ticket.body_md or ticket.title
    blockers = unit_services.close_unit(_unit_of(ticket), reason, ticket=ticket)
    return {"blockers": blockers}


def _publish_offer(ticket):
    from apps.catalogue import services as catalogue
    from apps.catalogue.models import Offer

    offer = Offer.objects.get(pk=ticket.action_payload["offer_id"])
    member = ticket.author
    catalogue.publish_offer(offer, member, approved_by=ticket)
    return {"offer": offer.pk}


def _verify_licence(ticket):
    from django.utils import timezone

    from apps.members.models import Licence

    licence = Licence.objects.get(pk=ticket.action_payload["licence_id"])
    licence.status, licence.verified_at, licence.decided_by = "verified", timezone.now(), ticket.number
    licence.save(update_fields=["status", "verified_at", "decided_by"])
    audit.record("system", "licence.verified", licence, ticket=ticket.number)
    return {"licence": licence.pk}


def _reject_licence(ticket):
    from apps.members.models import Licence

    licence = Licence.objects.get(pk=ticket.action_payload["licence_id"])
    licence.status, licence.decided_by = "rejected", ticket.number
    licence.save(update_fields=["status", "decided_by"])
    audit.record("system", "licence.rejected", licence, ticket=ticket.number)
    return {"licence": licence.pk}


def _hours_correct(ticket):
    from apps.units import services as unit_services
    from apps.units.models import HoursEntry

    p = ticket.action_payload
    entry = HoursEntry.objects.get(pk=p["entry_id"])
    reason = _("Correction decided in %(number)s: %(title)s") % {"number": ticket.number, "title": ticket.title}
    entry = unit_services.correct_hours(entry, int(p["minutes"]), reason)
    return {"entry": entry.pk, "minutes": entry.minutes}


def _hours_confirm(ticket):
    """The review found the numbers plausible. A ticket that carries a correction makes it instead."""
    if ticket.action_payload.get("entry_id"):
        return _hours_correct(ticket)
    return {"confirmed": True}


def _suspend_member(ticket):
    from apps.members import services as member_services
    from apps.members.models import Member

    member = Member.objects.get(number=ticket.action_payload["newer"])
    member_services.suspend(member, _("one person with two accounts, decided in %(n)s") % {"n": ticket.number})
    return {"suspended": member.number}


def _pause_unit(ticket):
    """A panel said a unit that opened with an amber check should not keep working: pause it, tell its workers."""
    from apps.units import services as unit_services

    from . import confirm

    unit = _unit_of(ticket)
    unit_services.pause_unit(unit, _("paused after a review (%(number)s)") % {"number": ticket.number})
    reasons = [r["reason"] for r in confirm.reasons(ticket)]
    when = ticket.petition_until.strftime("%Y-%m-%d") if ticket.petition_until else ""
    text = _(
        "The unit %(unit)s was paused after members reviewed it (%(number)s). "
        "Anyone can start a petition for a vote of all members until %(when)s. Reasons given: %(reasons)s."
    ) % {"unit": unit.name, "number": ticket.number, "reasons": "; ".join(reasons) or "-", "when": when}
    for w in unit_services.workers(unit):
        notify(w.member, text, f"/tickets/{ticket.number}/", email=True)
    return {"unit": unit.slug, "status": "paused"}


def _none(ticket):
    return {}


register("open_unit", _open_unit, _need("unit_id"))
register("close_unit", _close_unit, _need("unit_id"))
register("publish_offer", _publish_offer, _need("offer_id"))
register("verify_licence", _verify_licence, _need("licence_id"))
register("reject_licence", _reject_licence)
register("hours_confirm", _hours_confirm)
register("hours_correct", _hours_correct, _need("entry_id", "minutes"))
register("suspend_member", _suspend_member, _need("newer"))
register("pause_unit", _pause_unit, _need("unit_id"))
register("none", _none)
