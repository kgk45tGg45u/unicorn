"""The planning group (docs/05 section 8, P11.T04): drawn at random, advised by experts, paid for its work."""

import math
import random
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.hashing import sha256_hex
from apps.core.notify import notify
from apps.members.models import Member
from apps.rules.services import get_param
from apps.tickets import draw as ticket_draw
from apps.tickets.models import Confirmation

from . import services
from .models import ExpertAdviser, GroupDecision, GroupSeat, PlanningGroup

ACCEPT_DAYS = 7
ADVISER_DAYS = 14


def group_size(members: int) -> int:
    size = int(get_param("plan.group_size"))
    if members >= 3 * size:
        return size
    return max(int(get_param("plan.group_min")), math.ceil(float(get_param("plan.group_share_if_small")) * members))


def _previous_numbers(period, kind) -> list[str]:
    """The members of the last group of this kind; they are not drawn again."""
    last = PlanningGroup.objects.filter(kind=kind).exclude(period=period).order_by("-id").first()
    return list(last.seats.values_list("member__number", flat=True)) if last else []


def draw_group(period, kind="yearly", on=None, exclude_numbers=()) -> PlanningGroup:
    """Draw the group with the same verifiable method as other draws (a `Confirmation` anyone can repeat)."""
    from apps.tickets import services as ticket_services

    on = on or services.today()
    with transaction.atomic():
        if PlanningGroup.objects.filter(period=period, kind=kind).exists():
            raise services.PlanError(_("The group of this period was already drawn."))
        ticket = ticket_services.create_ticket(
            "plan_group",
            None,
            _("Planning group %(year)s") % {"year": period.starts_on.year}
            + ("" if kind == "yearly" else " (" + _("long-term") + ")"),
            body=_("The randomly drawn group that turns the proposals into whole plans."),
            action_payload={
                "members": [*_previous_numbers(period, kind), *exclude_numbers],
                "period": period.pk,
                "kind": kind,
            },
        )
        members = ticket_draw.eligible(ticket, "confirmers")
        total = Member.objects.filter(status=Member.MEMBER, deleted=False).count()
        k = group_size(total)
        fp = ticket_draw._fingerprint()
        seed = ticket_draw._seed(ticket.number, "group", 0, fp.hash if fp else ticket_draw.NO_FINGERPRINT)
        members = sorted(members, key=lambda m: m.number)
        chosen = random.Random(int(seed, 16)).sample(members, min(k, len(members)))
        confirmation = Confirmation.objects.create(
            ticket=ticket,
            round="group",
            size=k,
            seed=seed,
            fingerprint_date=fp.date if fp else None,
            eligible_count=len(members),
            eligible_hash=sha256_hex(",".join(m.number for m in members)),
        )
        group = PlanningGroup.objects.create(
            period=period,
            kind=kind,
            ticket=ticket,
            confirmation=confirmation,
            accept_until=on + timedelta(days=ACCEPT_DAYS),
            advisers_until=on + timedelta(days=ADVISER_DAYS),
        )
        for i, m in enumerate(chosen, start=1):
            GroupSeat.objects.create(group=group, member=m, drawn_order=i)
            notify(
                m,
                _("You were drawn for the planning group. Please accept or decline within %(n)s days.")
                % {"n": ACCEPT_DAYS},
                f"/plan/group/{group.pk}/",
                email=True,
            )
        audit.record("system", "plan.group_drawn", group, seated=len(chosen), eligible=len(members), size=k)
        return group


def active_seats(group):
    return group.seats.filter(replaced=False).exclude(accepted=False).select_related("member")


def is_seat(member, group) -> bool:
    return active_seats(group).filter(member=member).exists()


def _replace(group, old):
    """Draw one more member, with the same method; members already seated or drawn before are excluded."""
    from apps.tickets import services as ticket_services  # noqa: F401

    ticket = group.ticket
    taken = list(group.seats.values_list("member__number", flat=True))
    ticket.action_payload = {**ticket.action_payload, "members": [*ticket.action_payload["members"], *taken]}
    ticket.save(update_fields=["action_payload"])
    members = sorted(ticket_draw.eligible(ticket, "confirmers"), key=lambda m: m.number)
    fp = ticket_draw._fingerprint()
    draw_no = ticket.confirmations.count()
    seed = ticket_draw._seed(ticket.number, "replacement", draw_no, fp.hash if fp else ticket_draw.NO_FINGERPRINT)
    chosen = random.Random(int(seed, 16)).sample(members, min(1, len(members)))
    Confirmation.objects.create(
        ticket=ticket,
        parent=group.confirmation,
        round="replacement",
        size=1,
        seed=seed,
        fingerprint_date=fp.date if fp else None,
        eligible_count=len(members),
        eligible_hash=sha256_hex(",".join(m.number for m in members)),
    )
    for m in chosen:
        order = group.seats.count() + 1
        GroupSeat.objects.create(group=group, member=m, drawn_order=order)
        notify(
            m,
            _("You were drawn for the planning group. Please accept or decline within %(n)s days.")
            % {"n": ACCEPT_DAYS},
            f"/plan/group/{group.pk}/",
            email=True,
        )
    return chosen


def answer(seat, accept: bool):
    """A drawn member accepts or declines; a decliner is replaced."""
    with transaction.atomic():
        seat = GroupSeat.objects.select_for_update().get(pk=seat.pk)
        if seat.accepted is not None or seat.replaced:
            raise services.PlanError(_("You already answered."))
        seat.accepted = bool(accept)
        if not accept:
            seat.replaced = True
        seat.save(update_fields=["accepted", "replaced"])
        if not accept:
            _replace(seat.group, seat)
        return seat


def expire_unanswered(on=None) -> int:
    """After 7 days a drawn member who did not answer counts as declining, and is replaced."""
    on = on or services.today()
    done = 0
    for seat in GroupSeat.objects.filter(accepted__isnull=True, replaced=False, group__accept_until__lt=on):
        with transaction.atomic():
            seat.replaced = True
            seat.accepted = False
            seat.save(update_fields=["replaced", "accepted"])
            _replace(seat.group, seat)
            done += 1
    return done


# --- Expert advisers ---


def volunteer_adviser(member, group, statement, on=None):
    """Until unions exist, any member may offer to advise for 14 days (docs/05 section 8)."""
    from apps.members import services as member_services

    on = on or services.today()
    if not member_services.is_verified(member):  # HF-13
        raise services.PlanError(_("Only verified members can advise the planning group."))
    if group.advisers_until is None or on > group.advisers_until:
        raise services.PlanError(_("The time to offer advice for this group is over."))
    if is_seat(member, group):
        raise services.PlanError(_("Members of the group cannot also be its advisers."))
    adviser, _created = ExpertAdviser.objects.get_or_create(
        group=group, member=member, defaults={"statement": (statement or "").strip()}
    )
    return adviser


def propose_adviser(group, member, adviser):
    """A seat proposes to approve an adviser; the seats decide by majority, up to `plan.experts_max`."""
    return open_decision(
        group,
        member,
        "adviser",
        _("Approve %(who)s as an adviser") % {"who": adviser.member.number},
        {"adviser": adviser.pk},
    )


# --- Decisions of the group's seats (a simple majority) ---


def open_decision(group, member, kind, subject, payload=None) -> GroupDecision:
    if not is_seat(member, group):
        raise services.PlanError(_("Only members of the planning group can propose decisions."))
    return GroupDecision.objects.create(group=group, kind=kind, subject=subject[:200], payload=payload or {})


def vote(decision, member, yes: bool):
    """Only the group's seats vote; advisers and everyone else cannot (docs/05 section 8)."""
    with transaction.atomic():
        decision = GroupDecision.objects.select_for_update().get(pk=decision.pk)
        if not is_seat(member, decision.group):
            raise services.PlanError(_("Only members of the planning group vote on its decisions."))
        if decision.status != "open":
            raise services.PlanError(_("This decision is already made."))
        decision.votes = {**decision.votes, member.number: "yes" if yes else "no"}
        seats = active_seats(decision.group).count()
        need = seats // 2 + 1
        yes_n = sum(1 for v in decision.votes.values() if v == "yes")
        no_n = sum(1 for v in decision.votes.values() if v == "no")
        if yes_n >= need:
            decision.status, decision.decided_at = "approved", timezone.now()
            decision.save()
            _effect(decision)
        elif no_n > seats - need:
            decision.status, decision.decided_at = "rejected", timezone.now()
            decision.save()
        else:
            decision.save()
        return decision


def _effect(decision):
    from .models import PlanProposal, PlanVariant

    p = decision.payload
    if decision.kind == "adviser":
        adviser = ExpertAdviser.objects.get(pk=p["adviser"])
        if adviser.group.advisers.filter(approved=True).count() >= int(get_param("plan.experts_max")):
            decision.status = "rejected"
            decision.save(update_fields=["status"])
            return
        adviser.approved = True
        adviser.save(update_fields=["approved"])
    elif decision.kind == "include":
        from . import variants

        variants.include_proposal(PlanVariant.objects.get(pk=p["variant"]), PlanProposal.objects.get(pk=p["proposal"]))
    elif decision.kind == "submit":
        from . import variants

        variants.mark_submitted(PlanVariant.objects.get(pk=p["variant"]))


# --- Paid group work ---


def week_minutes(member, day) -> int:
    from django.db.models import Sum

    from apps.units.models import HoursEntry

    monday = day - timedelta(days=day.weekday())
    total = HoursEntry.objects.filter(
        member=member, ref_type="planning_group", date__gte=monday, date__lt=monday + timedelta(days=7)
    ).aggregate(t=Sum("minutes"))["t"]
    return total or 0


def record_hours(member, group, minutes, note=""):
    """Hours of the group's work, approved by the system up to the weekly cap per member."""
    from apps.units import services as unit_services

    if not is_seat(member, group):
        raise services.PlanError(_("Only members of the planning group record planning hours."))
    today = services.today()
    cap = int(float(get_param("plan.group_hours_cap_per_week")) * 60)
    allowed = cap - week_minutes(member, today)
    if allowed <= 0:
        raise services.PlanError(_("You have reached this week's limit of paid planning hours."))
    paid = min(int(minutes), allowed)
    entry = unit_services.record_coordination(
        member, paid, note or _("Planning group"), ref_type="planning_group", ref_id=str(group.pk)
    )
    return entry, int(minutes) - paid


def draw_long_term_group(period, on=None) -> PlanningGroup:
    """With multi-year plans a second group drafts the long-term part, and shares no member with the yearly group."""
    if int(get_param("plan.period_years")) <= 1:
        raise services.PlanError(_("Long-term plans exist only when a period is longer than one year."))
    yearly = PlanningGroup.objects.filter(period=period, kind="yearly").first()
    numbers = list(yearly.seats.values_list("member__number", flat=True)) if yearly else []
    return draw_group(period, kind="long_term", on=on, exclude_numbers=numbers)
