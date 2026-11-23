"""The confirmers' steps and the panel of 12 (docs/05 section 3).

All four confirmers must say yes (owner, 2026-11-21). One "no" starts a panel. A panel approves with 7 yes votes.
"""

from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.jobs import enqueue
from apps.core.notify import notify
from apps.members import services as member_services
from apps.rules.services import get_param

from . import draw as drawing
from . import services as ticket_services
from .models import Confirmation, Conflict, Seat

MIN_REASON = 20
MAX_WRONG = 2


class SeatError(ValueError):
    """A plain-words reason why a seat cannot do something."""


# --- Starting a round ---


def start_confirmers(ticket):
    """Draw the confirmers and wait for their answers."""
    if not drawing.eligible(ticket):
        ticket_services.set_status(ticket, "open", _("Waiting until members can be drawn to look at this ticket."))
        return None
    hours = get_param("governance.units.post_check_days") * 24 if ticket.type == "post_check_unit" else None
    confirmation = drawing.draw(ticket, "confirmers", ticket_services.seat_count(ticket), deadline_hours=hours)
    ticket_services.set_status(ticket, "confirming", ticket.status_note)
    schedule_deadline_job()
    return confirmation


def schedule_deadline_job(delay_minutes=10):
    """Queue the next run of `tickets.seat_deadlines`. One job per ten-minute slot."""
    when = timezone.now() + timedelta(minutes=delay_minutes)
    slot = f"{when:%Y%m%d%H}{when.minute // 10}"
    return enqueue("tickets.seat_deadlines", {}, run_after=when, dedupe_key=f"tickets.seat_deadlines:{slot}")


def start_panel(ticket):
    if not drawing.eligible(ticket):
        _reject(ticket, _("There were not enough members to form a panel."))
        return None
    confirmation = drawing.draw(ticket, "panel", get_param("governance.panel.size"))
    ticket_services.set_status(ticket, "panel", ticket.status_note)
    audit.record("system", "ticket.panel_started", ticket)
    return confirmation


# --- A member's seat ---


def active_seats(root):
    """The seats that still count in this round: not replaced, in the round's draw or its replacements."""
    return list(Seat.objects.filter(confirmation__in=_family(root), replaced=False).select_related("member"))


def _family(root):
    return Confirmation.objects.filter(Q(pk=root.pk) | Q(parent=root))


def seat_state(seat) -> str:
    """What the seat can do now: check, vote or nothing."""
    if seat.replaced or seat.vote is not None:
        return "done"
    if seat.confirmation.root.status != "open":
        return "closed"
    if timezone.now() >= seat.deadline:
        return "late"
    return "vote" if seat.check_passed else "check"


def open_seat(seat):
    if seat.opened_at is None:
        seat.opened_at = timezone.now()
        seat.save(update_fields=["opened_at"])


def answer_check(seat, choice) -> bool:
    """Answer the check question. After two wrong answers the seat is replaced. Returns True when right."""
    with transaction.atomic():
        seat = Seat.objects.select_for_update().get(pk=seat.pk)
        if seat_state(seat) != "check":
            raise SeatError(_("This seat is not waiting for an answer."))
        ticket = seat.confirmation.ticket
        try:
            right = int(choice) == ticket.check_correct
        except (TypeError, ValueError):
            raise SeatError(_("Please choose one of the answers.")) from None
        if right:
            seat.check_passed = True
            seat.save(update_fields=["check_passed"])
            audit.record(seat.member.number, "seat.check_passed", seat)
            return True
        seat.check_attempts += 1
        seat.save(update_fields=["check_attempts"])
        audit.record(seat.member.number, "seat.check_failed", seat, attempts=seat.check_attempts)
        if seat.check_attempts >= MAX_WRONG:
            replace_seat(seat, _("did not pass the check question"))
        return False


def cast(seat, vote, reason="", anonymous=False, ranking=None):
    """Vote yes or no after passing the check. Pays the review time. Then the round is evaluated.

    When a delegate is chosen from several applicants, a yes comes with a ranking, best first."""
    if vote not in ("yes", "no"):
        raise SeatError(_("Please answer yes or no."))
    reason = (reason or "").strip()
    if vote == "no" and len(reason) < MIN_REASON:
        raise SeatError(_("Please say why in at least %(n)s characters.") % {"n": MIN_REASON})
    with transaction.atomic():
        seat = Seat.objects.select_for_update().get(pk=seat.pk)
        if not member_services.is_verified(seat.member):  # HF-13
            raise SeatError(_("Only verified members can confirm."))
        state = seat_state(seat)
        if state == "check":
            raise SeatError(_("Please answer the check question first."))
        if state != "vote":
            raise SeatError(_("This seat can no longer vote."))
        ranking = _checked_ranking(seat.confirmation.ticket, vote, ranking)
        seat.vote, seat.reason, seat.voted_at, seat.ranking = vote, reason, timezone.now(), ranking
        seat.answered, seat.anonymous = True, bool(anonymous)
        seat.save(update_fields=["vote", "reason", "voted_at", "answered", "anonymous", "ranking"])
        audit.record(seat.member.number, "seat.voted", seat, vote=vote)
        _pay(seat)
        evaluate(seat.confirmation.root)
        return seat


def _checked_ranking(ticket, vote, ranking):
    """For a choice between several applicants, a yes must rank at least one of them, each at most once."""
    applicants = (ticket.action_payload or {}).get("applicants") if ticket.type == "delegate_choice" else None
    if not applicants or len(applicants) < 2 or vote != "yes":
        return None
    try:
        ranking = [int(i) for i in (ranking or [])]
    except (TypeError, ValueError):
        ranking = []
    if not ranking or len(set(ranking)) != len(ranking) or not set(ranking) <= set(applicants):
        raise SeatError(_("Please rank at least one of the applicants, best first, each only once."))
    return ranking


def _pay(seat):
    """Every seat that answers is paid as coordination hours (docs/05 section 3 item 8)."""
    from apps.units import services as unit_services

    ticket = seat.confirmation.ticket
    if ticket.type == "one_person_check":
        minutes = get_param("governance.one_person_units.check_minutes")
    elif seat.confirmation.root.round == "panel":
        minutes = get_param("governance.panel.review_minutes")
    else:
        minutes = get_param("governance.confirmers.review_minutes")
    if not minutes:
        return
    try:
        entry = unit_services.record_coordination(
            seat.member,
            minutes,
            _("Reviewed %(number)s") % {"number": ticket.number},
            ref_type="seat",
            ref_id=seat.pk,
        )
    except unit_services.UnitError as e:  # a closed month must not stop a vote
        audit.record("system", "seat.pay_failed", seat, error=str(e))
        return
    seat.paid_entry = entry
    seat.save(update_fields=["paid_entry"])


def declare_conflict(seat):
    """'I have a conflict of interest': the member is replaced and never drawn for this ticket again."""
    with transaction.atomic():
        seat = Seat.objects.select_for_update().get(pk=seat.pk)
        if seat_state(seat) not in ("check", "vote"):
            raise SeatError(_("This seat can no longer be changed."))
        Conflict.objects.get_or_create(ticket=seat.confirmation.ticket, member=seat.member)
        audit.record(seat.member.number, "seat.conflict", seat)
        replace_seat(seat, _("declared a conflict of interest"))


def replace_seat(seat, why):
    """Replace a seat with a newly drawn member. If nobody is left, the seat counts as a 'no'."""
    root = seat.confirmation.root
    ticket = seat.confirmation.ticket
    chain = 0
    s = seat
    while s.replaces_id:
        chain += 1
        s = s.replaces
    allowed = chain < get_param("governance.confirmers.max_replacements")
    new = None
    if allowed:
        deadline_hours = get_param(
            "governance.panel.deadline_hours" if root.round == "panel" else "governance.confirmers.deadline_hours"
        )
        replacement = drawing.draw(ticket, "replacement", 1, parent=root, replaces=seat, deadline_hours=deadline_hours)
        new = replacement.seats.first()
    seat.replaced = new is not None
    if new is None:
        seat.vote, seat.reason, seat.voted_at = "no", _("No answer: %(why)s") % {"why": why}, timezone.now()
    seat.save(update_fields=["replaced", "vote", "reason", "voted_at"])
    audit.record("system", "seat.replaced" if new else "seat.counted_as_no", seat, why=str(why))
    if new is None:
        evaluate(root)
    return new


# --- Counting ---


def needed(root, n):
    """How many yes votes approve, for n seats."""
    if root.round == "panel":
        return get_param("governance.panel.majority") if n >= get_param("governance.panel.size") else n // 2 + 1
    if root.ticket.type == "trust_review":  # the elected trust review group decides by majority (docs/07 section 5)
        return n // 2 + 1
    rule = get_param("governance.confirmers.rule")
    if rule == "all_but_one":
        return max(n - 1, 1)
    if rule == "majority":
        return n // 2 + 1
    return n  # all_yes


def evaluate(root):
    """Approve, reject or wait. Safe to call twice."""
    with transaction.atomic():
        root = Confirmation.objects.select_for_update().get(pk=root.pk)
        if root.status != "open":
            return root.status
        seats = active_seats(root)
        n = len(seats)
        yes = sum(1 for s in seats if s.vote == "yes")
        no = sum(1 for s in seats if s.vote == "no")
        need = needed(root, n)
        ticket = root.ticket
        if n and yes >= need:
            root.status = "approved"
            root.save(update_fields=["status"])
            if (ticket.action_payload or {}).get("then") == "referendum" and ticket.status != "referendum":
                _start_referendum(ticket)  # the confirmers only checked that the proposal is complete
                return "approved"
            from . import actions

            actions.approve(ticket, how=root.round)
            return "approved"
        if n == 0 or no > n - need:
            root.status = "rejected"
            root.save(update_fields=["status"])
            if root.round == "confirmers" and ticket.type != "trust_review":  # the group's majority is final
                start_panel(ticket)
            else:
                _reject(ticket, _("The panel did not approve it."))
            return "rejected"
        return "open"


def _start_referendum(ticket):
    """After a completeness check the vote of all members follows (docs/01 section 4, docs/01 section 3)."""
    from apps.members.models import PrivateFile
    from apps.votes import services as vote_services

    p = ticket.action_payload
    args = dict(p.get("referendum") or {})
    forecast = PrivateFile.objects.filter(pk=p["forecast_id"]).first() if p.get("forecast_id") else None
    question = p.get("question") or ticket.title
    vote_services.schedule_referendum(ticket, question, forecast=forecast, **args)


def _reject(ticket, note):
    """A final 'no' after the panel: the petition time starts (P07 builds the petition itself)."""
    from . import actions

    days = get_param("governance.petition.days")
    ticket.petition_until = timezone.now() + timedelta(days=days)
    ticket.save(update_fields=["petition_until"])
    ticket_services.set_status(ticket, "rejected", note)
    when = ticket.petition_until.strftime("%Y-%m-%d")
    text = _("%(number)s was not approved. Anyone can start a petition for a vote of all members until %(when)s.") % {
        "number": ticket.number,
        "when": when,
    }
    people = {s.member for c in ticket.confirmations.all() for s in c.seats.all()}
    if ticket.author_id:
        people.add(ticket.author)
    for m in people:
        notify(m, text, f"/tickets/{ticket.number}/")
    actions.reject(ticket)


def reasons(ticket):
    """Every 'no' reason of both rounds, without names unless the member chose to show them (docs/05 section 3)."""
    rows = []
    for s in Seat.objects.filter(confirmation__ticket=ticket, vote="no", answered=True).select_related("member"):
        rows.append({"reason": s.reason, "name": None if s.anonymous else s.member.display_name})
    return rows


# --- Deadlines (a job, every ten minutes) ---


def process_deadlines(now=None):
    """Replace silent seats, count missing votes as 'no', and send reminders. Safe to run twice."""
    now = now or timezone.now()
    open_seats = Seat.objects.filter(vote__isnull=True, replaced=False, confirmation__status="open").exclude(
        confirmation__round="mediation"
    )
    late = 0
    for seat in open_seats.filter(deadline__lte=now).select_related("confirmation", "member"):
        if seat.confirmation.root.status != "open":
            continue
        replace_seat(seat, _("did not answer in time"))
        late += 1
    for seat in open_seats.filter(
        deadline__gt=now, deadline__lte=now + timedelta(hours=24), reminded_at__isnull=True
    ).select_related("confirmation", "member"):
        notify(
            seat.member,
            _("Reminder: please answer for %(number)s within 24 hours.") % {"number": seat.confirmation.ticket.number},
            f"/seat/{seat.pk}/",
            email=True,
        )
        seat.reminded_at = now
        seat.save(update_fields=["reminded_at"])
    from . import mediation

    mediation.process_deadlines(now)
    # Tickets that found nobody to draw yet are tried again.
    from .models import Ticket

    for ticket in Ticket.objects.filter(status="open", decision_method="confirmers", confirmations__isnull=True):
        start_confirmers(ticket)
    return late


def seat_rows(ticket):
    """What the ticket page shows about the deciders: 'Confirmer 1-4' until decided, then names (unless anonymous)."""
    rounds = []
    for root in ticket.confirmations.filter(parent__isnull=True):
        decided = root.status != "open"
        title = _("Panel") if root.round == "panel" else _("Confirmers")
        label = _("Panel member %(n)s") if root.round == "panel" else _("Confirmer %(n)s")
        rows = []
        seats = Seat.objects.filter(confirmation__in=_family(root), replaced=False).select_related("member")
        for i, s in enumerate(seats.order_by("confirmation_id", "drawn_order"), start=1):
            row = {"label": label % {"n": i}, "name": None, "vote": None, "reason": ""}
            if s.vote is not None:
                row["answered"] = True
            if decided:
                row["name"] = None if s.anonymous else s.member.display_name
                row["vote"] = s.vote
                row["reason"] = s.reason if s.vote == "no" else ""
            rows.append(row)
        rounds.append({"title": title, "status": root.status, "rows": rows, "confirmation": root})
    return rounds
