"""How the units app and the tickets app meet: every council decision also has a ticket (P06.T07)."""

from django.utils.translation import gettext as _

from . import actions
from . import services as ticket_services
from .models import Ticket


def decision_opened(decision):
    """A council opened a decision: make its `council_decision` ticket, unless a ticket opened the decision."""
    if (decision.payload or {}).get("ticket"):
        return
    ticket = ticket_services.create_ticket(
        "council_decision",
        decision.opened_by,
        decision.title,
        decision.text,
        scope="unit",
        scope_unit=decision.unit,
        action_payload={"council_decision": decision.pk},
    )
    decision.payload = {**(decision.payload or {}), "ticket": ticket.number}
    decision.save(update_fields=["payload"])


def decision_closed(decision):
    """The council's tally decides the ticket."""
    number = (decision.payload or {}).get("ticket")
    ticket = Ticket.objects.filter(number=number).first() if number else None
    if ticket is None or ticket.status not in ("open", "draft"):
        return
    if decision.status == "approved":
        actions.approve(ticket, how="council")
    else:
        note = _("The council did not approve it (%(yes)s yes, %(no)s no).") % {
            "yes": decision.result.get("yes", 0),
            "no": decision.result.get("no", 0),
        }
        ticket_services.set_status(ticket, "rejected", note)
        actions.reject(ticket)
