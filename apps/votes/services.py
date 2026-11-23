"""Petitions, referendums and secret ballots (docs/05 sections 3 and 4)."""

import math
import secrets
from datetime import datetime, time, timedelta
from decimal import Decimal
from fractions import Fraction

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.hashing import sha256_hex
from apps.members import services as member_services
from apps.rules.services import get_param

from . import irv as irv_module
from .models import Ballot, Petition, PetitionSignature, Referendum, VoterRecord

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

# Functions called with (referendum) when a referendum is scheduled without anybody having said no. The tasks app
# adds one that asks a random member to write the "against" brief as a paid task (P07.T08).
AGAINST_BRIEF_HOOKS: list = []


class VoteError(ValueError):
    """A plain-words reason why something cannot be done."""


def _berlin_midnight(day):
    from apps.ledger.services import BERLIN

    return datetime.combine(day, time.min, tzinfo=BERLIN)


def eligible_now() -> int:
    """Active, verified members (HF-13)."""
    return member_services.active_members().count()


# --- Petitions ---


def petition_threshold() -> int:
    share = Decimal(str(get_param("governance.petition.share")))
    return max(get_param("governance.petition.min_signatures"), math.ceil(share * eligible_now()))


def open_petition(ticket, member, question=""):
    """Any verified member may start a petition while the petition time of a rejected ticket runs, or for a request."""
    if not member_services.is_verified(member):  # HF-13
        raise VoteError(_("Only verified members can start a petition."))
    now = timezone.now()
    with transaction.atomic():
        from apps.tickets.models import Ticket

        ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
        after_panel = ticket.status == "rejected" and ticket.petition_until and now < ticket.petition_until
        request = ticket.type == "referendum_request" and ticket.status == "open"
        if not (after_panel or request):
            raise VoteError(_("A petition cannot be started for this ticket now."))
        if ticket.petitions.filter(status="open").exists():
            raise VoteError(_("A petition is already open for this ticket."))
        petition = Petition.objects.create(
            ticket=ticket,
            question=(question or ticket.title)[:300],
            opened_by=member,
            opens_at=now,
            closes_at=now + timedelta(days=get_param("governance.petition.days")),
            threshold=petition_threshold(),
        )
        ticket.status, ticket.status_note = "petition", _("A petition is collecting signatures.")
        ticket.save(update_fields=["status", "status_note"])
        audit.record(member.number, "petition.opened", petition, ticket=ticket.number)
        sign(petition, member)
        return petition


def sign(petition, member):
    """Sign once. When the signatures reach the threshold, a referendum is scheduled."""
    if not member_services.is_verified(member):  # HF-13
        raise VoteError(_("Only verified members can sign a petition."))
    with transaction.atomic():
        petition = Petition.objects.select_for_update().get(pk=petition.pk)
        if petition.status != "open" or timezone.now() >= petition.closes_at:
            raise VoteError(_("This petition is closed."))
        try:
            with transaction.atomic():
                PetitionSignature.objects.create(petition=petition, member=member)
        except IntegrityError:
            raise VoteError(_("You already signed this petition.")) from None
        audit.record(member.number, "petition.signed", petition)
        if petition.signatures.count() >= petition.threshold:
            petition.status = "succeeded"
            petition.save(update_fields=["status"])
            audit.record("system", "petition.succeeded", petition)
            schedule_referendum(petition.ticket, petition.question)
        return petition


def close_petitions(now=None) -> int:
    """Petitions past their time without enough signatures fail, and the ticket goes back to rejected."""
    now = now or timezone.now()
    count = 0
    for p in Petition.objects.filter(status="open", closes_at__lte=now).select_related("ticket"):
        with transaction.atomic():
            p = Petition.objects.select_for_update().get(pk=p.pk)
            if p.status != "open":
                continue
            p.status = "failed"
            p.save(update_fields=["status"])
            from apps.tickets import services as ticket_services

            ticket_services.set_status(p.ticket, "rejected", _("The petition did not get enough signatures."))
            audit.record("system", "petition.failed", p)
            count += 1
    return count


# --- Referendums ---


def schedule_referendum(
    ticket, question, method="yes_no", options=None, days=None, quorum=None, majority=None, forecast=None
):
    """Schedule a vote of all members. It opens at 00:00 (Europe/Berlin) the next day."""
    from apps.tickets import confirm
    from apps.tickets import services as ticket_services

    days = days or get_param("governance.referendum.days")
    quorum = Decimal(str(quorum if quorum is not None else get_param("governance.referendum.quorum")))
    majority = majority or get_param("governance.referendum.majority")
    opens_at = _berlin_midnight(timezone.localdate() + timedelta(days=1))
    against = [r["reason"] for r in confirm.reasons(ticket)]
    with transaction.atomic():
        referendum = Referendum.objects.create(
            ticket=ticket,
            question=question[:300],
            method=method,
            options=options or [],
            brief_for_md=ticket.brief_md or ticket.body_md,
            brief_against_md="\n".join(f"- {r}" for r in against),
            forecast=forecast,
            opens_at=opens_at,
            closes_at=opens_at + timedelta(days=days),
            quorum_share=quorum,
            majority=majority,
        )
        ticket.decision_method = "referendum"
        ticket.save(update_fields=["decision_method"])
        ticket_services.set_status(ticket, "referendum", _("A vote of all members is scheduled."))
        audit.record("system", "referendum.scheduled", referendum, ticket=ticket.number)
        if not against:
            for hook in AGAINST_BRIEF_HOOKS:
                hook(referendum)
        return referendum


def open_due_referendums(now=None) -> int:
    now = now or timezone.now()
    count = 0
    for r in Referendum.objects.filter(status="scheduled", opens_at__lte=now):
        with transaction.atomic():
            r = Referendum.objects.select_for_update().get(pk=r.pk)
            if r.status != "scheduled":
                continue
            r.status, r.eligible_count = "open", eligible_now()
            r.save(update_fields=["status", "eligible_count"])
            audit.record("system", "referendum.opened", r, eligible=r.eligible_count)
            count += 1
    return count


def new_receipt() -> str:
    return "".join(secrets.choice(CROCKFORD) for _i in range(12))


def valid_choice(referendum, choice):
    if referendum.method == "yes_no":
        if choice not in ("yes", "no", "abstain"):
            raise VoteError(_("Please answer yes, no or abstain."))
        return choice
    if not isinstance(choice, list) or len(set(choice)) != len(choice) or not set(choice) <= set(referendum.options):
        raise VoteError(_("Please rank some of the options, each at most once."))
    return list(choice)


def cast(referendum, member, choice) -> str:
    """Vote once, in secret. Returns the receipt, which is shown once (HF-13)."""
    if not member_services.is_verified(member):  # HF-13
        raise VoteError(_("Only verified members can vote."))
    choice = valid_choice(referendum, choice)
    today = timezone.localdate()
    with transaction.atomic():
        referendum = Referendum.objects.select_for_update().get(pk=referendum.pk)
        if referendum.status != "open" or timezone.now() >= referendum.closes_at:
            raise VoteError(_("This vote is not open."))
        if member.verified_at is not None and member.verified_at > referendum.opens_at:
            raise VoteError(_("This vote was already open before you were verified."))
        try:
            with transaction.atomic():
                VoterRecord.objects.create(referendum=referendum, member=member, voted_on=today)
        except IntegrityError:
            raise VoteError(_("You have already voted.")) from None
        for _attempt in range(5):
            receipt = new_receipt()
            try:
                with transaction.atomic():
                    Ballot.objects.create(referendum=referendum, receipt=receipt, choice=choice)
                break
            except IntegrityError:
                continue
        else:
            raise VoteError(_("Something went wrong. Please try again."))
        audit.record(member.number, "referendum.voted", referendum)  # that the member voted, never how
        return receipt


def check_receipt(receipt):
    """What the ballot with this receipt says, so a member can see that it was counted."""
    ballot = Ballot.objects.filter(receipt=(receipt or "").strip().upper()).select_related("referendum__ticket").first()
    return ballot


# --- Counting ---


def count(referendum) -> dict:
    voters = referendum.voters.count()
    eligible = referendum.eligible_count
    turnout = Fraction(voters, eligible) if eligible else Fraction(0)
    quorum_met = turnout >= Fraction(referendum.quorum_share)
    choices = list(referendum.ballots.values_list("choice", flat=True))
    result = {
        "voters": voters,
        "eligible": eligible,
        "turnout": str(round(Decimal(turnout.numerator) / Decimal(turnout.denominator), 4)),
        "quorum_share": str(referendum.quorum_share),
        "quorum_met": bool(quorum_met),
        "majority": referendum.majority,
    }
    if referendum.method == "yes_no":
        yes, no, abstain = choices.count("yes"), choices.count("no"), choices.count("abstain")
        if referendum.majority == "two_thirds":
            majority_met = yes + no > 0 and Fraction(yes, yes + no) >= Fraction(2, 3)
        else:
            majority_met = yes + no > 0 and Fraction(yes, yes + no) > Fraction(1, 2)
        result.update(yes=yes, no=no, abstain=abstain, majority_met=bool(majority_met))
        result["approved"] = bool(quorum_met and majority_met)
    else:
        from apps.tickets.draw import NO_FINGERPRINT, _fingerprint

        fp = _fingerprint()
        seed = f"{referendum.ticket.number}:{referendum.pk}:{fp.hash if fp else NO_FINGERPRINT}"
        ranked = [c for c in choices if isinstance(c, list)]
        winner, rounds = irv_module.irv(ranked, list(referendum.options), seed)
        result.update(winner=winner, rounds=rounds, seed=sha256_hex(seed))
        result["approved"] = bool(quorum_met and winner is not None)
    return result


def close_referendums(now=None) -> int:
    """Count every referendum whose time is over, and let its ticket follow the result (P07.T04)."""
    now = now or timezone.now()
    done = 0
    for r in Referendum.objects.filter(status="open", closes_at__lte=now):
        with transaction.atomic():
            r = Referendum.objects.select_for_update().get(pk=r.pk)
            if r.status != "open":
                continue
            r.result = count(r)
            r.status = "closed"
            r.save(update_fields=["result", "status"])
            audit.record("system", "referendum.closed", r, approved=r.result["approved"])
            finish(r)
            done += 1
    return done


def finish(referendum):
    """The result decides the ticket, finally: a petition-forced vote has the last word."""
    from apps.tickets import actions
    from apps.tickets import services as ticket_services

    ticket = referendum.ticket
    result = referendum.result
    if result["approved"]:
        actions.approve(ticket, how="referendum")
        return
    if not result["quorum_met"]:
        why = _("Too few members voted (%(voters)s of %(eligible)s).") % result
    elif referendum.method == "yes_no":
        why = _("%(yes)s voted yes and %(no)s voted no.") % result
    else:
        why = _("No option won.")
    ticket.petition_until = None
    ticket.save(update_fields=["petition_until"])
    ticket_services.set_status(ticket, "rejected", why)
    actions.reject(ticket)
