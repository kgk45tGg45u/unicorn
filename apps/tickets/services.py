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
    scope_union=None,
    scope_area="",
    brief="",
    check=None,
    action_payload=None,
    plan_check=None,
    action=None,
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
    if scope == "union" and scope_union is None:
        raise TicketError(_("Please name the union."))
    _check_brief(info, brief, check)
    from . import actions

    action = action or info.action
    found = actions.problems(action, action_payload)
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
            scope_union=scope_union,
            scope_area=scope_area,
            brief_md=brief or "",
            check_question=check.get("question", ""),
            check_choices=list(check.get("choices") or []),
            check_correct=check.get("correct") or 0,
            check_hint=check.get("hint", ""),
            decision_method=info.method,
            action=action or "",
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


# --- Changing a default through its tier (P07.T05) ---


def create_parameter_change(author, key, value, reason, brief="", check=None):
    """Propose a new value for a default. The value is checked against its bounds before the ticket opens."""
    from django.core.exceptions import ValidationError

    from apps.rules.models import Parameter
    from apps.rules.services import validate_value

    p = Parameter.objects.filter(key=key).first()
    if p is None:
        raise TicketError(_("This default does not exist."))
    try:
        new = validate_value(
            key=p.key, type=p.type, value=value, min_value=p.min_value, max_value=p.max_value, choices=p.choices
        )
    except ValidationError as e:
        raise TicketError(" ".join(e.messages)) from e
    if not (reason or "").strip():
        raise TicketError(_("Please say why the default should change."))
    from .briefs import _check

    if not brief:
        brief = _("The default %(key)s is %(old)s. It is proposed to change it to %(new)s. Reason: %(reason)s") % {
            "key": key,
            "old": p.value,
            "new": new,
            "reason": reason.strip(),
        }
    if not check:
        check = _check(
            _("Which default is to be changed?"),
            key,
            ["economy.flat_tax.fixed_rate", "membership.vouches_needed"],
            _("the first sentence"),
        )
    return create_ticket(
        "parameter_change",
        author,
        _("Change %(key)s to %(new)s") % {"key": key, "new": new},
        brief=brief,
        check=check,
        action_payload={"key": key, "new_value": new, "reason": reason.strip(), "units": []},
    )


def turn_parameter_ticket(ticket, member, kind):
    """A plan-tier change that was sent away can become a request for a vote of all, or a plan proposal."""
    if ticket.type != "parameter_change" or ticket.status != "rejected":
        raise TicketError(_("This ticket cannot be turned into something else."))
    if kind == "referendum_request":
        return create_ticket(
            "referendum_request",
            member,
            ticket.title,
            ticket.body_md,
            brief=ticket.brief_md,
            action="change_parameter",
            action_payload=ticket.action_payload,
        )
    if kind == "plan_proposal":
        return create_ticket(
            "plan_proposal", member, ticket.title, ticket.brief_md, action_payload=ticket.action_payload
        )
    raise TicketError(_("Please choose what to turn it into."))


# --- Changing the hard frame (P07.T06) ---


def create_hard_frame_change(author, rule, new_text, why, code_change, authors, forecast, check=None, brief=""):
    """The expert proposal. Four confirmers check that it is complete, then all members vote (docs/01 section 4)."""
    problems = []
    if not (rule or "").strip():
        problems.append(_("Please name the rule or the bound that should change."))
    for label, text in (
        (_("the new text or value"), new_text),
        (_("why it is needed"), why),
        (_("what changes in the code"), code_change),
    ):
        if not (text or "").strip():
            problems.append(_("Please write %(what)s.") % {"what": label})
    if not authors or not all((a.get("name") or "").strip() and (a.get("expertise") or "").strip() for a in authors):
        problems.append(_("Please name the authors and one sentence about the expertise of each."))
    if forecast is None:
        problems.append(_("A forecast is required. Attach it as a file."))
    if problems:
        raise TicketError(" ".join(str(p) for p in problems))
    lines = [
        _("Rule or bound: %(rule)s") % {"rule": rule},
        _("New text or value: %(text)s") % {"text": new_text},
        _("Why it is needed: %(why)s") % {"why": why},
        _("What changes in the code: %(code)s") % {"code": code_change},
        _("Authors:"),
        *[f"- {a['name']}: {a['expertise']}" for a in authors],
        brief or "",
    ]
    return create_ticket(
        "hard_frame_change",
        author,
        _("Change the hard frame: %(rule)s") % {"rule": rule},
        brief="\n".join(str(x) for x in lines if x),
        check=check,
        action_payload={
            "rule": rule,
            "new_text": new_text,
            "why": why,
            "code_change": code_change,
            "authors": authors,
            "forecast_id": forecast.pk,
            "then": "referendum",
            "question": str(_("Should the hard frame change as proposed in the ticket?")),
            "referendum": {  # the hard parameters, never the ordinary referendum defaults
                "days": get_param("governance.hard_frame_change.days"),
                "quorum": str(get_param("governance.hard_frame_change.quorum")),
                "majority": get_param("governance.hard_frame_change.majority"),
            },
            "units": [],
        },
    )


def record_release(ticket, operator, tag, commit):
    """An operator records the release that carries an approved hard-frame change. The app never changes its code."""
    if not (operator.user.is_staff and (tag or "").strip() and (commit or "").strip()):
        raise TicketError(_("Only an operator can record a release, with its tag and commit."))
    if ticket.type != "hard_frame_change" or ticket.status != "in_action":
        raise TicketError(_("This ticket is not waiting for a release."))
    with transaction.atomic():
        ticket.action_result = {**ticket.action_result, "release": {"tag": tag.strip(), "commit": commit.strip()}}
        ticket.save(update_fields=["action_result"])
        audit.record(operator.number, "ticket.release_recorded", ticket, tag=tag.strip(), commit=commit.strip())
        return set_status(ticket, "done", _("Released as %(tag)s.") % {"tag": tag.strip()})
