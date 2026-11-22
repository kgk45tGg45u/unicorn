"""Tickets: making them, numbering them, and the steps that decide them (docs/05)."""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.rules.services import get_param

from . import types
from .models import Ticket, TicketCounter

MAX_BRIEF_WORDS = 500


class TicketError(ValueError):
    """A plain-words reason why something cannot be done."""


def seat_count(ticket) -> int:
    info = types.TYPES[ticket.type]
    return info.confirmers or get_param("governance.confirmers.size")


def _next_number() -> str:
    counter, _created = TicketCounter.objects.select_for_update().get_or_create(pk=1)
    counter.last += 1
    counter.save(update_fields=["last"])
    return f"T-{counter.last:06d}"


def _check_brief(info, brief, check):
    problems = []
    if len((brief or "").split()) > MAX_BRIEF_WORDS:
        problems.append(_("The brief may have at most %(n)s words.") % {"n": MAX_BRIEF_WORDS})
    if info.needs_brief:
        if not (brief or "").strip():
            problems.append(_("Please write a short brief for the people who will decide."))
        check = check or {}
        choices = check.get("choices") or []
        if not (check.get("question") or "").strip() or len(choices) != 3 or not all(str(c).strip() for c in choices):
            problems.append(_("Please add one check question with three answers."))
        elif check.get("correct") not in (0, 1, 2):
            problems.append(_("Please say which answer is correct."))
    if problems:
        raise TicketError(" ".join(problems))


def create_ticket(
    type,
    author,
    title,
    body="",
    *,
    scope="all",
    scope_unit=None,
    scope_area="",
    brief="",
    check=None,
    action_payload=None,
    plan_check=None,
    open_now=True,
):
    """Make a ticket. `check` is {"question", "choices": [3 texts], "correct": 0-2, "hint"}."""
    info = types.TYPES.get(type)
    if info is None:
        raise TicketError(_("This kind of ticket does not exist."))
    if not (title or "").strip():
        raise TicketError(_("Please give the ticket a title."))
    if scope not in types.SCOPES:
        raise TicketError(_("Please choose who the ticket is for."))
    if scope == "unit" and scope_unit is None:
        raise TicketError(_("Please name the unit."))
    _check_brief(info, brief, check)
    from . import actions

    found = actions.problems(info.action, action_payload)
    if found:
        raise TicketError(" ".join(found))
    check = check or {}
    with transaction.atomic():
        ticket = Ticket.objects.create(
            number=_next_number(),
            type=type,
            title=title.strip()[:160],
            body_md=body or "",
            author=author,
            scope=scope,
            scope_unit=scope_unit,
            scope_area=scope_area,
            brief_md=brief or "",
            check_question=check.get("question", ""),
            check_choices=list(check.get("choices") or []),
            check_correct=check.get("correct") or 0,
            check_hint=check.get("hint", ""),
            decision_method=info.method,
            action=info.action or "",
            action_payload=action_payload or {},
            plan_check=plan_check,
            status="open" if open_now else "draft",
        )
        audit.record(author.number if author else "system", "ticket.created", ticket, type=type)
        if open_now:
            open_ticket(ticket)
        return ticket


def open_ticket(ticket):
    """Send an open ticket to its deciders (the secretariat, P06.T03)."""
    from . import routing

    ticket.status = "open"
    ticket.save(update_fields=["status"])
    return routing.route(ticket)


def is_final(ticket) -> bool:
    return ticket.status in types.FINAL


def set_status(ticket, status, note=""):
    ticket.status = status
    ticket.status_note = note[:300]
    if status in ("approved", "rejected", "done", "expired", "withdrawn") and ticket.decided_at is None:
        ticket.decided_at = timezone.now()
    ticket.save(update_fields=["status", "status_note", "decided_at"])
    audit.record("system", "ticket.status", ticket, status=status)
    return ticket


# --- Comments, helpful marks, notifications ---

EDIT_MINUTES = 15


def _can_take_part(member) -> bool:
    return member is not None and member.status == "member"


def add_comment(ticket, member, body, parent=None):
    from .models import Comment

    if not _can_take_part(member):
        raise TicketError(_("Only members can write comments."))
    if not (body or "").strip():
        raise TicketError(_("Please write something."))
    if parent is not None and parent.ticket_id != ticket.pk:
        raise TicketError(_("This reply belongs to another ticket."))
    from apps.core.notify import notify

    with transaction.atomic():
        comment = Comment.objects.create(ticket=ticket, author=member, parent=parent, body_md=body.strip())
        audit.record(member.number, "ticket.comment", comment, ticket=ticket.number)
        url = f"/tickets/{ticket.number}/"
        text = _("New comment on %(number)s: %(title)s") % {"number": ticket.number, "title": ticket.title}
        if parent is not None and parent.author_id != member.pk:
            notify(parent.author, text, url)
        if ticket.author_id and ticket.author_id not in (member.pk, getattr(parent, "author_id", None)):
            notify(ticket.author, text, url)
        return comment


def edit_comment(comment, member, body, now=None):
    now = now or timezone.now()
    if comment.author_id != member.pk:
        raise TicketError(_("You can only change your own comments."))
    if now - comment.created_at > timedelta(minutes=EDIT_MINUTES):
        raise TicketError(_("A comment can only be changed in the first %(n)s minutes.") % {"n": EDIT_MINUTES})
    if not (body or "").strip():
        raise TicketError(_("Please write something."))
    with transaction.atomic():
        audit.record(member.number, "ticket.comment_edited", comment, before=comment.body_md)
        comment.body_md = body.strip()
        comment.edited_at = now
        comment.save(update_fields=["body_md", "edited_at"])
        return comment


def mark_helpful(comment, member):
    from django.db import IntegrityError

    from .models import HelpfulMark

    if not _can_take_part(member):
        raise TicketError(_("Only members can mark a comment as helpful."))
    if comment.author_id == member.pk:
        raise TicketError(_("You cannot mark your own comment as helpful."))
    try:
        with transaction.atomic():
            return HelpfulMark.objects.create(comment=comment, member=member)
    except IntegrityError:
        raise TicketError(_("You already marked this comment as helpful.")) from None


def status_words(status) -> str:
    return str(dict(Ticket.STATUSES).get(status, status))


def my_open_seats(member):
    """Seats this member still has to answer."""
    from .models import Seat

    return list(
        Seat.objects.filter(
            member=member,
            vote__isnull=True,
            replaced=False,
            confirmation__ticket__status__in=("confirming", "panel"),
            deadline__gt=timezone.now(),
        ).select_related("confirmation__ticket")
    )
