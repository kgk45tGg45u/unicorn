"""Flags: notice and action for content members find wrong (docs/05 section 9, the Digital Services Act)."""

from collections.abc import Callable
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.notify import notify
from apps.members import services as member_services
from apps.rules.services import get_param

from . import actions
from . import services as ticket_services
from .models import Flag, Hidden, Ticket

REASONS = {
    "illegal": _("It is illegal"),
    "wrong_data": _("The data is wrong, or it is fraud"),
    "harassment": _("It is harassment"),
    "privacy": _("It shows private data"),
    "other": _("Something else"),
}
TARGET_TYPES = ("offer", "comment", "ticket", "profile", "hours", "payment", "review", "guideline", "thanks")
# the model class name -> the flag's target type, for the template filter
CLASS_TO_TARGET = {
    "Offer": "offer",
    "Comment": "comment",
    "Ticket": "ticket",
    "Member": "profile",
    "HoursEntry": "hours",
    "Review": "review",
}


class FlagError(ValueError):
    """A plain-words reason why something cannot be done."""


@dataclass
class FlagTarget:
    """A kind of content another app lets members report: how to find it, who owns it, how to describe it."""

    model: type
    owners: Callable  # owners(obj) -> (members, unit ids)
    describe: Callable  # describe() -> "a thank-you"
    excerpt: Callable  # excerpt(obj) -> a short text for the confirmers


EXTRA_TARGETS: dict = {}


def register_target(name, target):
    """Let another app add a reportable kind (the name is at most 10 characters, the length of the column)."""
    EXTRA_TARGETS[name] = target


def _target(target_type, target_id):
    """The object a flag is about, or None (payments exist from phase 8)."""
    from apps.bodies.models import GuidelineDeclaration
    from apps.catalogue.models import Offer
    from apps.market.models import Review
    from apps.members.models import Member
    from apps.units.models import HoursEntry

    from .models import Comment

    model = {
        "offer": Offer,
        "comment": Comment,
        "ticket": Ticket,
        "profile": Member,
        "hours": HoursEntry,
        "review": Review,
        "guideline": GuidelineDeclaration,
    }.get(target_type)
    if model is None and target_type in EXTRA_TARGETS:
        model = EXTRA_TARGETS[target_type].model
    return model.objects.filter(pk=target_id).first() if model else None


def _owners(target_type, obj):
    """The members whose work or words are flagged, and the unit ids it concerns."""
    from apps.units import services as unit_services

    if obj is None:
        return [], []
    if target_type in EXTRA_TARGETS:
        return EXTRA_TARGETS[target_type].owners(obj)
    if target_type == "offer":
        return [w.member for w in unit_services.workers(obj.unit)], [obj.unit_id]
    if target_type in ("comment", "review"):
        return [obj.author], []
    if target_type == "ticket":
        return ([obj.author] if obj.author_id else []), []
    if target_type == "guideline":  # a declaration on an offer belongs to the offer's unit
        return [w.member for w in unit_services.workers(obj.offer.unit)], [obj.offer.unit_id]
    if target_type == "profile":
        return [obj], []
    if target_type == "hours":
        return [obj.member], [obj.unit_id]
    return [], []


def owners(target_type, target_id) -> list:
    return _owners(target_type, _target(target_type, target_id))[0]


def _describe(target_type):
    if target_type in EXTRA_TARGETS:
        return EXTRA_TARGETS[target_type].describe()
    return {
        "offer": _("an offer"),
        "comment": _("a comment"),
        "ticket": _("a ticket"),
        "profile": _("a profile"),
        "hours": _("an hours entry"),
        "payment": _("a payment"),
        "review": _("a review"),
        "guideline": _("a guideline declaration"),
    }[target_type]


def _excerpt(target_type, obj) -> str:
    if obj is None:
        return ""
    if target_type in EXTRA_TARGETS:
        return EXTRA_TARGETS[target_type].excerpt(obj)
    if target_type == "offer":
        return _("An offer of %(item)s by the unit %(unit)s.") % {"item": obj.item.name, "unit": obj.unit.name}
    if target_type == "comment":
        return f'"{obj.body_md[:300]}"'
    if target_type == "ticket":
        return f"{obj.number}: {obj.title}"
    if target_type == "guideline":
        return _("The unit %(unit)s says it follows the guideline %(title)s.") % {
            "unit": obj.offer.unit.name,
            "title": obj.guideline.title,
        }
    if target_type == "profile":
        return _("The profile of %(name)s.") % {"name": obj.display_name}
    if target_type == "hours":
        return _("%(minutes)s minutes for the unit %(unit)s on %(date)s.") % {
            "minutes": obj.minutes,
            "unit": obj.unit.name,
            "date": obj.date,
        }
    return f'"{obj.text[:300]}"'


def _new_ticket(member, target_type, target_id, obj, reason, people, unit_ids):
    from .briefs import _check

    check = _check(
        _("What reason was given for the report?"),
        str(REASONS[reason]),
        [str(v) for k, v in REASONS.items() if k != reason],
        _("the first sentence"),
    )
    brief = "\n".join(
        [
            _("A member reported %(what)s: %(reason)s.")
            % {"what": _describe(target_type), "reason": REASONS[reason].lower()},
            _excerpt(target_type, obj),
            _("Should this be removed or corrected? Yes removes it from view. No lets it stay."),
        ]
    )
    return ticket_services.create_ticket(
        "flag",
        member,
        _("Report: %(what)s") % {"what": _describe(target_type)},
        brief=brief,
        check=check,
        action_payload={
            "target_type": target_type,
            "target_id": target_id,
            "units": unit_ids,
            "members": [m.number for m in people],
        },
    )


def active_ticket(target_type, target_id):
    """The open flag ticket for this thing, if there is one."""
    flag = (
        Flag.objects.filter(target_type=target_type, target_id=target_id)
        .exclude(ticket__status__in=["done", "rejected", "approved", "withdrawn", "expired"])
        .select_related("ticket")
        .first()
    )
    return flag.ticket if flag else None


def flag(member, target_type, target_id, reason, text=""):
    """Report something. The first flag opens a ticket; later ones join it; enough different flaggers hide the thing."""
    if target_type not in TARGET_TYPES or reason not in REASONS:
        raise FlagError(_("Please say what you want to report and why."))
    if not member_services.is_verified(member):
        raise FlagError(_("Only members can report something."))
    obj = _target(target_type, target_id)
    if obj is None and target_type != "payment":
        raise FlagError(_("This can no longer be found."))
    people, unit_ids = _owners(target_type, obj)
    if member in people:
        raise FlagError(_("You cannot report your own work. If it is wrong, please change or remove it yourself."))
    with transaction.atomic():
        ticket = active_ticket(target_type, target_id)
        if ticket is None:
            ticket = _new_ticket(member, target_type, target_id, obj, reason, people, unit_ids)
        try:
            with transaction.atomic():
                row = Flag.objects.create(
                    target_type=target_type,
                    target_id=target_id,
                    reason=reason,
                    text=(text or "").strip()[:500],
                    created_by=member,
                    ticket=ticket,
                )
        except IntegrityError:
            raise FlagError(_("You already reported this.")) from None
        audit.record(member.number, "flag.created", row, target=f"{target_type}:{target_id}", ticket=ticket.number)
        flaggers = Flag.objects.filter(ticket=ticket).values("created_by").distinct().count()
        if flaggers >= get_param("governance.flags.hide_after_flags"):
            hide(target_type, target_id, ticket)
        return row


def hide(target_type, target_id, ticket):
    hidden, created = Hidden.objects.get_or_create(
        target_type=target_type, target_id=target_id, until=None, defaults={"ticket": ticket}
    )
    if created:
        audit.record("system", "flag.hidden", hidden, ticket=ticket.number)
    return hidden


def hidden_ids(target_type) -> set:
    return set(Hidden.objects.filter(target_type=target_type, until__isnull=True).values_list("target_id", flat=True))


def is_hidden(target_type, target_id) -> bool:
    return Hidden.objects.filter(target_type=target_type, target_id=target_id, until__isnull=True).exists()


def reasons_for(target_type, target_id) -> list[str]:
    """What the author sees next to their hidden thing: the reasons members gave."""
    rows = Flag.objects.filter(target_type=target_type, target_id=target_id).order_by("created_at")
    return [f"{REASONS[f.reason]}{': ' + f.text if f.text else ''}" for f in rows]


# --- The outcome ---


def _is_flag_ticket(ticket):
    return ticket.type == "flag" and ticket.action_payload.get("target_type")


def statement_of_reasons(ticket) -> str:
    """The DSA statement: what was reported, what was decided, who decided how, and how to contest."""
    from . import confirm

    p = ticket.action_payload
    flags = Flag.objects.filter(ticket=ticket).order_by("created_at")
    lines = [
        _("%(what)s was removed after members reported it.") % {"what": _describe(p["target_type"]).capitalize()},
        _("The reports said:"),
        *[f"- {REASONS[f.reason]}{': ' + f.text if f.text else ''}" for f in flags],
    ]
    seats = [s for c in ticket.confirmations.all() for s in c.seats.all() if s.answered]
    yes, no = sum(1 for s in seats if s.vote == "yes"), sum(1 for s in seats if s.vote == "no")
    lines.append(
        _("Members drawn by chance looked at it: %(yes)s said it should be removed, %(no)s said it should stay.")
        % {"yes": yes, "no": no}
    )
    against = [r["reason"] for r in confirm.reasons(ticket)]
    if against:
        lines.append(_("Reasons given for keeping it:"))
        lines.extend(f"- {r}" for r in against)
    lines.append(
        _("You can ask for a panel of 12 members to look at this again. Open the ticket %(number)s and choose this.")
        % {"number": ticket.number}
    )
    return "\n".join(lines)


# Functions called with (ticket, upheld) when a dispute ticket is decided. The trade fund settles payment mismatches.
DISPUTE_HOOKS: list = []


def _dispute_decided(ticket, upheld):
    for hook in DISPUTE_HOOKS:
        hook(ticket, upheld)
    return {"dispute": "recorded"}


def _remove(ticket):
    p = ticket.action_payload
    if p.get("dispute"):  # a dispute about an order is only recorded here; nothing is hidden
        return _dispute_decided(ticket, True)
    hide(p["target_type"], p["target_id"], ticket)
    statement = statement_of_reasons(ticket)
    for m in owners(p["target_type"], p["target_id"]):
        notify(
            m,
            _("A statement of reasons about %(number)s") % {"number": ticket.number},
            f"/tickets/{ticket.number}/",
            email=True,
        )
    return {"removed": True, "statement": statement}


def _keep(ticket):
    p = ticket.action_payload
    if p.get("dispute"):
        return _dispute_decided(ticket, False)
    Hidden.objects.filter(target_type=p["target_type"], target_id=p["target_id"], until__isnull=True).update(
        until=timezone.now()
    )
    original = p.get("contest_of") or ticket.number
    for f in Flag.objects.filter(ticket__number=original).select_related("created_by"):
        notify(
            f.created_by,
            _("Thank you for your report. Members looked at it and the content stays."),
            f"/tickets/{ticket.number}/",
        )
    return {"kept": True}


def _need_target(payload):
    return (
        []
        if payload.get("target_type") or payload.get("dispute") or payload.get("contest_of")
        else [_("This ticket does not say what it is about.")]
    )


actions.register("flag_remove", _remove, _need_target)
actions.register("flag_keep", _keep, _need_target)


def can_contest(ticket, member) -> bool:
    """The author of removed content may ask a panel of 12 to look again."""
    p = ticket.action_payload or {}
    if ticket.type != "flag" or not (ticket.action_result or {}).get("removed") or member is None:
        return False
    if any(
        (t.action_payload or {}).get("contest_of") == ticket.number for t in Ticket.objects.filter(type="flag_contest")
    ):
        return False
    return member in owners(p["target_type"], p["target_id"])


def contest(ticket, member):
    """Contest a removal: a panel of 12 (not the first confirmers) decides whether it should stand."""
    from .briefs import _check

    if not can_contest(ticket, member):
        raise FlagError(_("You cannot contest this, or it was already contested."))
    p = ticket.action_payload
    check = _check(
        _("Which ticket is being contested?"), ticket.number, ["T-000000", "T-999999"], _("the first sentence")
    )
    brief = _(
        "%(what)s was removed after a report (ticket %(number)s). Its author says this was wrong and asks you to "
        "look again. Yes means the removal was wrong and it comes back. No means it stays removed."
    ) % {"what": _describe(p["target_type"]).capitalize(), "number": ticket.number}
    return ticket_services.create_ticket(
        "flag_contest",
        member,
        _("Contest of %(number)s") % {"number": ticket.number},
        brief=brief,
        check=check,
        action_payload={**p, "contest_of": ticket.number},
    )
