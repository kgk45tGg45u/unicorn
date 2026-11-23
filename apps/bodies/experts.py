"""Expert advisers named by unions (docs/05 section 8, P13.T05).

A union only names a member. The member accepts, and the planning group still decides by majority, up to
`plan.experts_max`. Advisers never vote in the group.
"""

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.notify import notify
from apps.members import services as member_services
from apps.members.models import Member
from apps.plan import group as group_module
from apps.plan import services as plan_services
from apps.plan.models import ExpertAdviser, PlanningGroup

from . import services
from .models import ExpertNomination


def current_group(on=None):
    """The yearly planning group that is still looking for advisers, or None."""
    on = on or plan_services.today()
    return PlanningGroup.objects.filter(kind="yearly", advisers_until__gte=on).order_by("-id").first()


def nomination_problems(payload) -> list[str]:
    member = Member.objects.filter(number=(payload or {}).get("member", "")).first()
    if member is None or not member_services.is_verified(member):  # HF-13
        return [_("Please name a verified member as the adviser.")]
    group = current_group()
    if group is None:
        return [_("No planning group is looking for advisers now.")]
    if group_module.is_seat(member, group):
        return [_("Members of the group cannot also be its advisers.")]
    return []


def _nominate(decision):
    p = decision.payload
    problems = nomination_problems(p)
    if problems:
        raise services.BodyError(problems[0])
    member = Member.objects.get(number=p["member"])
    group = current_group()
    nomination, created = ExpertNomination.objects.get_or_create(
        union=decision.union,
        group=group,
        member=member,
        defaults={"decision": decision, "statement": (p.get("statement") or "").strip()},
    )
    if created:
        audit.record("system", "union.expert_named", decision.union, member=member.number)
        notify(
            member,
            _("The union %(union)s names you as an expert adviser for the planning group. Please accept or decline.")
            % {"union": decision.union.name},
            "/bodies/nominations/",
            email=True,
        )
    return {"nomination": nomination.pk}


def accept(nomination, member, on=None):
    """The member accepts. An `ExpertAdviser` row is made; the planning group still has to approve it."""
    on = on or plan_services.today()
    with transaction.atomic():
        nomination = ExpertNomination.objects.select_for_update().get(pk=nomination.pk)
        if nomination.member_id != member.pk or nomination.status != "pending":
            raise services.BodyError(_("This nomination is not waiting for your answer."))
        group = nomination.group
        if group.advisers_until is None or on > group.advisers_until:
            raise services.BodyError(_("The time to offer advice for this group is over."))
        if group_module.is_seat(member, group):
            raise services.BodyError(_("Members of the group cannot also be its advisers."))
        adviser, _created = ExpertAdviser.objects.get_or_create(
            group=group,
            member=member,
            defaults={"statement": nomination.statement, "nominated_by_union": nomination.union},
        )
        if adviser.nominated_by_union_id is None:  # the member had already volunteered: the union's name is added
            adviser.nominated_by_union = nomination.union
            adviser.save(update_fields=["nominated_by_union"])
        nomination.status, nomination.answered_at = "accepted", timezone.now()
        nomination.save(update_fields=["status", "answered_at"])
        audit.record(member.number, "union.expert_accepted", nomination.union)
        return adviser


def decline(nomination, member):
    with transaction.atomic():
        nomination = ExpertNomination.objects.select_for_update().get(pk=nomination.pk)
        if nomination.member_id != member.pk or nomination.status != "pending":
            raise services.BodyError(_("This nomination is not waiting for your answer."))
        nomination.status, nomination.answered_at = "declined", timezone.now()
        nomination.save(update_fields=["status", "answered_at"])
        audit.record(member.number, "union.expert_declined", nomination.union)
        return nomination


def pending_for(member):
    return ExpertNomination.objects.filter(member=member, status="pending").select_related("union", "group")


def register():
    services.register_action("nominate_expert", _nominate)
    services.EXTRA_PROBLEMS["nominate_expert"] = nomination_problems
