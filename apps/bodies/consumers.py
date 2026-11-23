"""Consumers' councils (docs/05 section 7, P13.T07): members around a topic. They have no special power.

They file tickets and flags like any member (each flag counts once per member, never per council), and they publish
guidelines that units may say they follow.
"""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.tally import count
from apps.members import services as member_services
from apps.units import services as unit_services

from . import services
from .models import (
    ConsumerCouncil,
    ConsumerMembership,
    Guideline,
    GuidelineDeclaration,
    GuidelineVote,
)

VOTE_DAYS = 7


def members(council):
    rows = ConsumerMembership.objects.filter(council=council, left_at__isnull=True).select_related("member")
    return [r.member for r in rows if member_services.is_verified(r.member) and not r.member.deleted]


def is_member(member, council) -> bool:
    return member is not None and member in members(council)


def create_council(member, name, topic, description=""):
    if not member_services.is_verified(member):  # HF-13
        raise services.BodyError(_("Only verified members can form a consumers' council."))
    name, topic = (name or "").strip(), (topic or "").strip()
    if not name or not topic:
        raise services.BodyError(_("Please give the council a name and a topic."))
    if ConsumerCouncil.objects.filter(name__iexact=name).exists():
        raise services.BodyError(_("There is already a consumers' council with this name."))
    with transaction.atomic():
        council = ConsumerCouncil.objects.create(name=name, topic=topic, description=description, created_by=member)
        ConsumerMembership.objects.create(council=council, member=member, joined_at=timezone.now())
        audit.record(member.number, "consumers.formed", council)
        return council


def join(member, council):
    if not member_services.is_verified(member):  # HF-13
        raise services.BodyError(_("Only verified members can join a consumers' council."))
    if council.status != "active":
        raise services.BodyError(_("This council is closed."))
    with transaction.atomic():
        row, created = ConsumerMembership.objects.get_or_create(
            council=council, member=member, left_at=None, defaults={"joined_at": timezone.now()}
        )
        if created:
            audit.record(member.number, "consumers.joined", council)
        return row


def leave(member, council):
    ConsumerMembership.objects.filter(council=council, member=member, left_at__isnull=True).update(
        left_at=timezone.now()
    )
    audit.record(member.number, "consumers.left", council)


# --- Guidelines: the members' majority, counted over 7 days ---


def propose_guideline(member, council, title, body):
    if not is_member(member, council):
        raise services.BodyError(_("Only members of the council can propose a guideline."))
    if not (title or "").strip() or not (body or "").strip():
        raise services.BodyError(_("A guideline needs a title and a text."))
    now = timezone.now()
    with transaction.atomic():
        guideline = Guideline.objects.create(
            council=council,
            title=title.strip()[:120],
            body_md=body,
            proposed_by=member,
            opens_at=now,
            closes_at=now + timedelta(days=VOTE_DAYS),
        )
        audit.record(member.number, "consumers.guideline_proposed", guideline)
        return guideline


def vote(guideline, member, choice):
    if choice not in ("yes", "no", "abstain"):
        raise services.BodyError(_("Please answer yes, no or abstain."))
    with transaction.atomic():
        guideline = Guideline.objects.select_for_update().get(pk=guideline.pk)
        if guideline.status != "voting" or timezone.now() >= guideline.closes_at:
            raise services.BodyError(_("This vote is closed."))
        if not is_member(member, guideline.council):
            raise services.BodyError(_("Only members of the council can vote."))
        if GuidelineVote.objects.filter(guideline=guideline, member=member).exists():
            raise services.BodyError(_("You have already voted."))
        GuidelineVote.objects.create(guideline=guideline, member=member, vote=choice)
        audit.record(member.number, "consumers.guideline_voted", guideline)
        everyone = {m.pk for m in members(guideline.council)}
        if everyone <= set(guideline.votes.values_list("member_id", flat=True)):
            tally(guideline)
        return guideline


def tally(guideline):
    """A majority of the members who vote decides. Safe to call twice."""
    with transaction.atomic():
        guideline = Guideline.objects.select_for_update().get(pk=guideline.pk)
        if guideline.status != "voting":
            return guideline
        everyone = {m.pk for m in members(guideline.council)}
        votes = [v.vote for v in guideline.votes.all() if v.member_id in everyone]
        counted = count(votes, "majority", 0, len(everyone))
        guideline.result = {"yes": counted.yes, "no": counted.no, "abstain": counted.abstain, "members": len(everyone)}
        if counted.approved:
            last = (
                Guideline.objects.filter(council=guideline.council, title=guideline.title, status="published")
                .order_by("-version")
                .first()
            )
            guideline.status, guideline.published_at = "published", timezone.now()
            guideline.version = (last.version + 1) if last else 1
        else:
            guideline.status = "rejected"
        guideline.save()
        audit.record("system", "consumers.guideline_closed", guideline, status=guideline.status)
        return guideline


def close_due_guidelines(now=None) -> int:
    done = 0
    for g in Guideline.objects.filter(status="voting", closes_at__lte=now or timezone.now()):
        tally(g)
        done += 1
    return done


def published(council):
    return council.guidelines.filter(status="published")


# --- Declarations on offers ---


def declare(member, offer, guideline):
    """A unit says it follows a guideline: its council decides, a one-person unit's member decides at once."""
    unit = offer.unit
    if guideline.status != "published" or guideline.council.status != "active":
        raise services.BodyError(_("This guideline is not published."))
    if not member_services.is_verified(member) or not unit_services.can_decide_joins(member, unit):
        raise services.BodyError(
            _("Only the unit's council, or the single worker of a one-person unit, can declare this.")
        )
    if GuidelineDeclaration.objects.filter(offer=offer, guideline=guideline, withdrawn_at__isnull=True).exists():
        raise services.BodyError(_("This offer already says it follows this guideline."))
    return unit_services.open_decision(
        member,
        unit,
        _("We follow the guideline %(title)s") % {"title": guideline.title},
        _("The unit says on its offer %(item)s that it follows the guideline %(title)s of %(council)s.")
        % {"item": offer.item.name, "title": guideline.title, "council": guideline.council.name},
        kind="guideline",
        payload={"guideline": guideline.pk, "offer": offer.pk},
    )


def _declare_action(decision):
    from apps.catalogue.models import Offer

    p = decision.payload
    guideline, offer = Guideline.objects.get(pk=p["guideline"]), Offer.objects.get(pk=p["offer"])
    declaration, created = GuidelineDeclaration.objects.get_or_create(
        guideline=guideline,
        offer=offer,
        withdrawn_at=None,
        defaults={"declared_by": decision.opened_by, "declared_at": timezone.now()},
    )
    if created:
        audit.record("system", "consumers.declared", offer, guideline=guideline.pk)


def withdraw_declaration(member, declaration):
    if not unit_services.can_edit_unit(member, declaration.offer.unit):
        raise services.BodyError(_("Only the unit's responsible or council can take this down."))
    declaration.withdrawn_at = timezone.now()
    declaration.save(update_fields=["withdrawn_at"])
    audit.record(member.number, "consumers.declaration_withdrawn", declaration.offer)


def declarations_for(offer):
    """What the offer page shows: declarations that were not withdrawn or hidden after reports."""
    from apps.tickets import flags

    hidden = flags.hidden_ids("guideline")
    rows = offer.guideline_declarations.filter(withdrawn_at__isnull=True).select_related("guideline__council")
    return [d for d in rows if d.pk not in hidden and d.guideline.status == "published"]


def register():
    unit_services.DECISION_ACTIONS["guideline"] = _declare_action
