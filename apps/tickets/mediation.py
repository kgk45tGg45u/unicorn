"""Mediation: three mediators from the volunteers, then a panel of 12 if they find no agreement (docs/05 section 9)."""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.notify import notify
from apps.members.models import Member
from apps.rules.services import get_param

from . import actions, draw
from . import services as ticket_services
from .models import MediationMessage, Seat, Ticket

MAX_POSITION_WORDS = 300
MAX_MEDIATOR_MINUTES = 360  # six hours per mediation are paid by the system


class MediationError(ValueError):
    """A plain-words reason why something cannot be done."""


def party_numbers(ticket) -> list[str]:
    return list(ticket.action_payload.get("members", []))


def is_party(member, ticket) -> bool:
    from apps.units import services as unit_services
    from apps.units.models import Unit

    p = ticket.action_payload
    if member.number in p.get("members", []):
        return True
    return any(unit_services.is_worker(member, u) for u in Unit.objects.filter(pk__in=p.get("units", [])))


def mediators(ticket):
    return Member.objects.filter(
        seats__confirmation__ticket=ticket, seats__confirmation__round="mediation", seats__replaced=False
    ).distinct()


def is_mediator_of(member, ticket) -> bool:
    return mediators(ticket).filter(pk=member.pk).exists()


def open_mediation(author, title, body, parties_members=(), parties_units=(), brief="", check=None):
    """A member asks for mediation. `parties_*` name the other side (the asking member is a party too)."""
    members = {author.number, *(m.number for m in parties_members)}
    units = [u.pk for u in parties_units]
    if len(members) + len(units) < 2:
        raise MediationError(_("Mediation needs two sides. Please name the other member or unit."))
    return ticket_services.create_ticket(
        "mediation",
        author,
        title,
        body,
        brief=brief,
        check=check,
        action_payload={"members": sorted(members), "units": units, "positions": {}, "confirmed": []},
    )


def start(ticket):
    """Draw the mediators from the volunteers, excluding the parties; if there are too few, from everyone eligible."""
    k = get_param("governance.mediation.mediators")
    pool = set(Member.objects.filter(is_mediator=True).values_list("pk", flat=True))
    candidates = [m for m in draw.eligible(ticket, "mediation") if m.pk in pool]
    only = pool if len(candidates) >= k else None
    if not draw.eligible(ticket, "mediation"):
        ticket_services.set_status(ticket, "open", _("Waiting until mediators can be drawn."))
        return None
    days = get_param("governance.mediation.days")
    confirmation = draw.draw(ticket, "mediation", k, only=only, deadline_hours=days * 24, needs_check=False)
    ticket_services.set_status(ticket, "confirming", _("With the mediators until %(date)s.") % {"date": _date(days)})
    return confirmation


def _date(days):
    return (timezone.now() + timedelta(days=days)).strftime("%Y-%m-%d")


def _may_see(member, ticket) -> bool:
    return member is not None and (is_party(member, ticket) or is_mediator_of(member, ticket))


def post(ticket, member, body):
    if not _may_see(member, ticket):
        raise MediationError(_("Only the parties and the mediators can write here."))
    if ticket.status != "confirming":
        raise MediationError(_("This mediation is closed."))
    if not (body or "").strip():
        raise MediationError(_("Please write something."))
    msg = MediationMessage.objects.create(ticket=ticket, author=member, body=body.strip())
    for other in {*Member.objects.filter(number__in=party_numbers(ticket)), *mediators(ticket)} - {member}:
        notify(
            other,
            _("New message in the mediation %(number)s") % {"number": ticket.number},
            f"/tickets/{ticket.number}/mediation/",
        )
    return msg


def messages_for(ticket, member):
    return list(ticket.mediation_messages.select_related("author")) if _may_see(member, ticket) else []


def write_position(ticket, member, text):
    """Each party writes one position of at most 300 words; the panel reads them if there is no agreement."""
    if not is_party(member, ticket):
        raise MediationError(_("Only the parties can write a position."))
    if len((text or "").split()) > MAX_POSITION_WORDS:
        raise MediationError(_("A position may have at most %(n)s words.") % {"n": MAX_POSITION_WORDS})
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
        positions = dict(ticket.action_payload.get("positions", {}))
        positions[member.number] = (text or "").strip()
        ticket.action_payload = {**ticket.action_payload, "positions": positions}
        ticket.save(update_fields=["action_payload"])
        return ticket


def propose_agreement(ticket, mediator, text):
    """A mediator writes the agreement. Both sides must confirm it."""
    if not is_mediator_of(mediator, ticket):
        raise MediationError(_("Only the mediators can write the agreement."))
    if ticket.status != "confirming" or not (text or "").strip():
        raise MediationError(_("Please write the agreement."))
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
        ticket.action_payload = {**ticket.action_payload, "agreement": text.strip(), "confirmed": []}
        ticket.save(update_fields=["action_payload"])
        for m in Member.objects.filter(number__in=party_numbers(ticket)):
            notify(
                m,
                _("An agreement was proposed in %(number)s. Please read it.") % {"number": ticket.number},
                f"/tickets/{ticket.number}/mediation/",
            )
        return ticket


def _sides(ticket):
    """Each side as a list of the members who can speak for it: single members and the workers of unit parties."""
    from apps.units import services as unit_services
    from apps.units.models import Unit

    sides = [[m] for m in Member.objects.filter(number__in=party_numbers(ticket))]
    for u in Unit.objects.filter(pk__in=ticket.action_payload.get("units", [])):
        sides.append([w.member for w in unit_services.workers(u)])
    return sides


def confirm_agreement(ticket, member):
    """A party confirms the agreement. When every side has, the ticket is done."""
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
        p = ticket.action_payload
        if ticket.status != "confirming" or not p.get("agreement"):
            raise MediationError(_("There is no agreement to confirm."))
        if not is_party(member, ticket):
            raise MediationError(_("Only the parties can confirm the agreement."))
        confirmed = set(p.get("confirmed", [])) | {member.number}
        ticket.action_payload = {**p, "confirmed": sorted(confirmed)}
        ticket.save(update_fields=["action_payload"])
        if all(any(m.number in confirmed for m in side) for side in _sides(ticket)):
            actions.approve(ticket, how="agreement")
        return ticket


def no_agreement(ticket, member):
    """A mediator says there is no agreement: a panel of 12 decides between the positions."""
    if not is_mediator_of(member, ticket) and not is_party(member, ticket):
        raise MediationError(_("Only the mediators or the parties can say this."))
    return to_panel(ticket)


def to_panel(ticket):
    from . import confirm

    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
        if ticket.status != "confirming" or ticket.confirmations.filter(round="panel").exists():
            return ticket
        positions = ticket.action_payload.get("positions", {})
        lines = [ticket.brief_md, ""]
        for i, (number, text) in enumerate(positions.items(), start=1):
            lines += [_("Position %(n)s (%(number)s):") % {"n": i, "number": number}, text, ""]
        lines.append(
            _(
                "Do you side with the member who asked for mediation? "
                "Yes means the asking side. No means the other side."
            )
        )
        ticket.brief_md = "\n".join(lines).strip()
        ticket.save(update_fields=["brief_md"])
        audit.record("system", "mediation.to_panel", ticket)
        confirm.start_panel(ticket)
        return ticket


def process_deadlines(now=None):
    """Mediations past their time without an agreement go to a panel. Safe to run twice."""
    now = now or timezone.now()
    late = Seat.objects.filter(confirmation__round="mediation", replaced=False, deadline__lte=now)
    count = 0
    for ticket in Ticket.objects.filter(pk__in=late.values("confirmation__ticket_id")):
        if ticket.status == "confirming":
            to_panel(ticket)
            count += 1
    return count


def record_time(ticket, mediator, minutes):
    """Mediators record their real time; the system approves up to six hours per mediation."""
    from apps.units import services as unit_services

    if not is_mediator_of(mediator, ticket):
        raise MediationError(_("Only the mediators record time here."))
    if not isinstance(minutes, int) or minutes < 1:
        raise MediationError(_("Please enter the minutes you worked."))
    from apps.units.models import HoursEntry

    already = sum(
        e.minutes for e in HoursEntry.objects.filter(member=mediator, ref_type="mediation", ref_id=str(ticket.pk))
    )
    if already + minutes > MAX_MEDIATOR_MINUTES:
        raise MediationError(_("At most %(h)s hours are paid for one mediation.") % {"h": MAX_MEDIATOR_MINUTES // 60})
    return unit_services.record_coordination(
        mediator, minutes, _("Mediation %(number)s") % {"number": ticket.number}, ref_type="mediation", ref_id=ticket.pk
    )


def _decided(ticket):
    p = ticket.action_payload
    if p.get("agreement") and ticket.status == "approved" and p.get("confirmed"):
        return {"outcome": "agreement", "text": p["agreement"]}
    side = "the asking side" if ticket.status == "approved" else "the other side"
    return {"outcome": "panel", "text": str(_("The panel sided with %(side)s.") % {"side": side})}


actions.register("mediation_decided", _decided)
