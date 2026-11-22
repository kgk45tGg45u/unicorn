"""Briefs and check questions for tickets the app makes itself (P06.T07). Member numbers only, never personal data."""

import random

from django.utils.translation import gettext as _

from .services import create_ticket


def _check(question, right, others, hint):
    """A check question with three answers: the right one hidden among two others, in a fixed order."""
    choices = [right] + [o for o in others if o != right][:2]
    while len(choices) < 3:
        choices.append(_("None of these"))
    random.Random(f"{question}{right}").shuffle(choices)
    return {"question": question, "choices": choices, "correct": choices.index(right), "hint": hint}


def _points(result):
    return [{"color": p.color, "text": p.text} for p in result.points]


def open_unit(unit, member, result):
    from apps.units.models import Unit

    kinds = {k: str(label) for k, label in Unit.KINDS if k != "coordination"}
    lines = [
        _("%(member)s wants to open the unit %(name)s.") % {"member": member.number, "name": unit.name},
        _("It is a %(kind)s unit.") % {"kind": kinds.get(unit.kind, unit.kind)},
        unit.description or "",
        _("The plan check says:"),
        *[f"- {p.text}" for p in result.points],
        _("Do you agree that it should open?"),
    ]
    check = _check(
        _("What kind of unit is %(name)s?") % {"name": unit.name},
        kinds.get(unit.kind, unit.kind),
        [v for k, v in kinds.items() if k != unit.kind],
        _("the kind of unit"),
    )
    return create_ticket(
        "open_unit",
        member,
        _("Open the unit %(name)s") % {"name": unit.name},
        brief="\n".join(x for x in lines if x),
        check=check,
        action_payload={"unit_id": unit.pk, "units": [unit.pk]},
        plan_check={"color": result.color, "points": _points(result)},
    )


def post_check_unit(unit, member, result):
    check = _check(
        _("What is the name of the unit under review?"),
        unit.name,
        [_("A different unit"), _("No unit")],
        _("the first sentence"),
    )
    lines = [
        _("The unit %(name)s opened at once, with these points from the plan check:") % {"name": unit.name},
        *[f"- {p.text}" for p in result.points if p.color != "green"],
        _("Should this unit keep working?"),
    ]
    return create_ticket(
        "post_check_unit",
        None,
        _("Review of the unit %(name)s") % {"name": unit.name},
        brief="\n".join(lines),
        check=check,
        action_payload={"unit_id": unit.pk, "units": [unit.pk]},
        plan_check={"color": result.color, "points": _points(result)},
    )


def offer_red_check(offer, member, result):
    check = _check(
        _("Which item is the offer for?"),
        offer.item.name,
        [_("Another item"), _("Nothing")],
        _("the first sentence"),
    )
    lines = [
        _("%(member)s wants to publish an offer of %(item)s for the unit %(unit)s.")
        % {"member": member.number, "item": offer.item.name, "unit": offer.unit.name},
        _("The plan check says:"),
        *[f"- {p.text}" for p in result.points],
        _("Should the offer be published?"),
    ]
    return create_ticket(
        "offer_red_check",
        member,
        _("Publish the offer of %(item)s") % {"item": offer.item.name},
        brief="\n".join(lines),
        check=check,
        action_payload={"offer_id": offer.pk, "units": [offer.unit_id]},
        plan_check={"color": result.color, "points": _points(result)},
    )


def verify_licence(licence):
    kinds = {k: str(label) for k, label in licence.KINDS}
    check = _check(
        _("Which licence is to be checked?"),
        kinds.get(licence.kind, licence.kind),
        [v for k, v in kinds.items() if k != licence.kind],
        _("the first sentence"),
    )
    brief = _(
        "Member %(number)s says they hold a %(kind)s licence. Open the document on this page and check that it shows "
        "a valid licence of that kind and that it belongs to this member. Do not share what you see."
    ) % {"number": licence.member.number, "kind": kinds.get(licence.kind, licence.kind)}
    return create_ticket(
        "verify_licence",
        licence.member,
        _("Check a %(kind)s licence") % {"kind": kinds.get(licence.kind, licence.kind)},
        brief=brief,
        check=check,
        action_payload={"licence_id": licence.pk, "document_id": licence.document_id},
    )


def _open_ticket_exists(type, key, value) -> bool:
    from .models import Ticket

    return any(
        (t.action_payload or {}).get(key) == value
        for t in Ticket.objects.filter(type=type).exclude(status__in=["done", "rejected", "withdrawn", "expired"])
    )


def duplicate_suspected(newer, older, kind):
    if _open_ticket_exists("duplicate_suspected", "members", [newer.number, older.number]):
        return None
    kinds = {
        "email": _("email address"),
        "phone": _("phone number"),
        "iban": _("bank account"),
        "name_birth": _("name and birth date"),
    }
    check = _check(
        _("What do the two accounts have in common?"),
        str(kinds.get(kind, kind)),
        [str(v) for k, v in kinds.items() if k != kind],
        _("the first sentence"),
    )
    brief = _(
        "The accounts %(a)s and %(b)s share the same %(kind)s. Decide: do both accounts belong to the same person? "
        "Yes means one person with two accounts, and the newer account is suspended. No means two different people."
    ) % {"a": older.number, "b": newer.number, "kind": kinds.get(kind, kind)}
    return create_ticket(
        "duplicate_suspected",
        None,
        _("Is %(a)s the same person as %(b)s?") % {"a": older.number, "b": newer.number},
        brief=brief,
        check=check,
        action_payload={"newer": newer.number, "older": older.number, "members": [newer.number, older.number]},
    )


def hours_review(offer, kind, month, value, extra=""):
    what = (
        _("The hours paid to this unit differ from the hours its output should need.")
        if kind == "hours"
        else _("The inputs this unit received are higher than its output needs.")
    )
    check = _check(
        _("What is this review about?"),
        _("Hours and output") if kind == "hours" else _("Inputs and output"),
        [_("Hours and output"), _("Inputs and output"), _("Prices")],
        _("the first sentence"),
    )
    brief = "\n".join(
        [
            _("Unit %(unit)s, offer of %(item)s, month %(month)s.")
            % {"unit": offer.unit.name, "item": offer.item.name, "month": f"{month:%Y-%m}"},
            what,
            _("The measured gap is %(value)s.") % {"value": value},
            extra,
            _("Do the numbers look plausible to you? Yes confirms them. No sends the matter to a panel."),
        ]
    )
    return create_ticket(
        "hours_review",
        None,
        _("Review the numbers of %(unit)s for %(month)s") % {"unit": offer.unit.name, "month": f"{month:%Y-%m}"},
        brief=brief,
        check=check,
        action_payload={"offer_id": offer.pk, "kind": kind, "month": f"{month:%Y-%m}", "units": [offer.unit_id]},
    )


def one_person_check(unit, member, month, minutes):
    check = _check(_("Which unit is checked?"), unit.name, [_("Another unit"), _("No unit")], _("the first sentence"))
    brief = _(
        "The unit %(unit)s has one worker, %(member)s. In %(month)s the worker recorded %(hours)s hours. Look at the "
        "unit's public page and its offers. Do the hours look plausible for what the unit made?"
    ) % {"unit": unit.name, "member": member.number, "month": f"{month:%Y-%m}", "hours": f"{minutes / 60:.1f}"}
    return create_ticket(
        "one_person_check",
        None,
        _("Check the hours of %(unit)s") % {"unit": unit.name},
        brief=brief,
        check=check,
        action_payload={"unit_id": unit.pk, "month": f"{month:%Y-%m}", "units": [unit.pk], "members": [member.number]},
    )


def audit_failure(run):
    from .models import Ticket

    if Ticket.objects.filter(type="audit_failure").exclude(status__in=["done", "rejected", "approved"]).exists():
        return None  # one open ticket is enough; the nightly check would otherwise open one every night
    n = len(run.findings)
    check = _check(
        _("How many findings did the audit report?"), str(n), [str(n + 1), str(n + 2)], _("the first sentence")
    )
    brief = "\n".join(
        [_("The nightly check of the books found %(n)s problem(s):") % {"n": n}, *[f"- {f}" for f in run.findings[:20]]]
    )
    return create_ticket(
        "audit_failure",
        None,
        _("The books failed an audit"),
        brief=brief,
        check=check,
        action_payload={"audit_run": run.pk},
    )


def dispute(author, reason_label, what, unit, ref):
    reasons = [_("Not received"), _("Damaged"), _("Not performed")]
    check = _check(
        _("What did the member report?"), str(reason_label), [str(r) for r in reasons], _("the first sentence")
    )
    brief = _(
        "A member reports a problem with %(what)s from %(unit)s: %(reason)s. "
        "The UNIQ stay reserved until it is settled."
    ) % {
        "what": what,
        "unit": unit.name,
        "reason": str(reason_label).lower(),
    }
    return create_ticket(
        "flag",
        author,
        _("Problem with an order from %(unit)s") % {"unit": unit.name},
        brief=brief,
        check=check,
        action_payload={"dispute": {"reason": str(reason_label), **ref}, "units": [unit.pk]},
    )
