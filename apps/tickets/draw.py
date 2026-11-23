"""A random draw anyone can check (docs/05 section 3)."""

import random
from datetime import timedelta

from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.hashing import sha256_hex
from apps.core.notify import notify
from apps.members.models import Member, SiteState
from apps.rules.services import get_param

from .models import Confirmation, Seat

NO_FINGERPRINT = "0" * 64


def _month_start():
    from apps.ledger.services import BERLIN

    now = timezone.now().astimezone(BERLIN)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _units_of(ticket):
    ids = set()
    if ticket.scope_unit_id:
        ids.add(ticket.scope_unit_id)
    payload = ticket.action_payload or {}
    ids.update(payload.get("units", []))
    if payload.get("unit_id"):
        ids.add(payload["unit_id"])
    return ids


def eligible(ticket, round="confirmers") -> list[Member]:
    """Everyone who may be drawn for this ticket, sorted by member number (docs/05 section 3)."""
    from apps.members.services import _add_months
    from apps.units.models import UnitMembership

    now = timezone.now()
    members = Member.objects.filter(status=Member.MEMBER, deleted=False)  # HF-13
    state = SiteState.get()
    founders_exempt = state.launched_at is None or now < _add_months(state.launched_at, 12)
    old_enough = _add_months(now, -get_param("governance.confirmers.min_member_months"))
    from django.db.models import Q

    long_enough = Q(joined_at__lte=old_enough)
    if founders_exempt:
        long_enough |= Q(is_founder=True)
    members = members.filter(long_enough)
    if ticket.author_id:
        members = members.exclude(pk=ticket.author_id)
    unit_ids = _units_of(ticket)
    if unit_ids:
        members = members.exclude(
            pk__in=UnitMembership.objects.filter(unit_id__in=unit_ids, left_at__isnull=True).values("member_id")
        )
    if ticket.type in ("audit_failure", "trust_review"):
        from apps.votes.elections import current_members

        role = "auditor" if ticket.type == "audit_failure" else "trust_review"
        elected = list(current_members(role).values_list("pk", flat=True))
        if elected:  # until they are elected, random confirmers look at it
            members = members.filter(pk__in=elected)
    members = members.exclude(number__in=(ticket.action_payload or {}).get("members", []))
    members = members.exclude(seats__confirmation__ticket=ticket)
    contested = (ticket.action_payload or {}).get("contest_of")
    if contested:  # a panel that looks again never includes the first deciders
        members = members.exclude(seats__confirmation__ticket__number=contested)
    members = members.exclude(conflicts__ticket=ticket)
    members = members.filter(Q(draw_pause_until__isnull=True) | Q(draw_pause_until__lt=timezone.localdate()))
    if ticket.scope == "local" and ticket.scope_area:
        members = members.filter(postcode__startswith=ticket.scope_area)
    chosen = []
    limit = get_param("governance.confirmers.max_draws_per_month")
    start = _month_start()
    for m in members.order_by("number").distinct():
        if Seat.objects.filter(member=m, confirmation__created_at__gte=start).count() < limit:
            chosen.append(m)
    return chosen


def _fingerprint():
    from apps.ledger.models import DailyFingerprint

    return DailyFingerprint.objects.filter(chain="uniq", date__lt=timezone.localdate()).order_by("-date").first()


def _seed(ticket_number, round, draw_no, fingerprint_hash):
    return sha256_hex(f"{ticket_number}:{round}:{draw_no}:{fingerprint_hash}")


def draw(
    ticket, round, k, *, parent=None, only=None, replaces=None, deadline_hours=None, needs_check=True
) -> Confirmation:
    """Draw up to `k` members and seat them. `only` limits the pool (mediators)."""
    members = eligible(ticket, round)
    if only is not None:
        members = [m for m in members if m.pk in only]
    members = sorted(members, key=lambda m: m.number)
    fp = _fingerprint()
    draw_no = ticket.confirmations.count()
    seed = _seed(ticket.number, round, draw_no, fp.hash if fp else NO_FINGERPRINT)
    chosen = random.Random(int(seed, 16)).sample(members, min(k, len(members)))
    confirmation = Confirmation.objects.create(
        ticket=ticket,
        parent=parent,
        round=round,
        size=k,
        seed=seed,
        fingerprint_date=fp.date if fp else None,
        eligible_count=len(members),
        eligible_hash=sha256_hex(",".join(m.number for m in members)),
    )
    if deadline_hours is None:
        deadline_hours = get_param(
            "governance.panel.deadline_hours" if round == "panel" else "governance.confirmers.deadline_hours"
        )
    deadline = timezone.now() + timedelta(hours=deadline_hours)
    for i, m in enumerate(chosen, start=1):
        seat = Seat.objects.create(
            confirmation=confirmation,
            member=m,
            drawn_order=i,
            deadline=deadline,
            replaces=replaces,
            check_passed=not (needs_check and ticket.check_question),
        )
        seat.notified_at = timezone.now()
        seat.save(update_fields=["notified_at"])
        notify(
            m,
            _("You were drawn to look at %(number)s: %(title)s. Please answer by %(when)s.")
            % {"number": ticket.number, "title": ticket.title, "when": deadline.strftime("%Y-%m-%d %H:%M")},
            f"/seat/{seat.pk}/",
            email=True,
        )
    audit.record(
        "system",
        "ticket.draw",
        confirmation,
        ticket=ticket.number,
        round=round,
        seated=len(chosen),
        eligible=len(members),
    )
    if len(chosen) < k and round != "replacement":
        ticket.status_note = _("Only %(n)s members could be drawn.") % {"n": len(chosen)}
        ticket.save(update_fields=["status_note"])
    return confirmation


def reproduce(confirmation, member_numbers) -> list[str]:
    """Repeat a draw from the list of numbers an auditor was given. Returns the numbers drawn, in order."""
    numbers = sorted(member_numbers)
    if sha256_hex(",".join(numbers)) != confirmation.eligible_hash or len(numbers) != confirmation.eligible_count:
        raise ValueError(_("This list is not the list the draw used."))
    return random.Random(int(confirmation.seed, 16)).sample(numbers, min(confirmation.size, len(numbers)))
