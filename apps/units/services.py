from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.members import services as member_services
from apps.rules.services import get_param

from .models import JoinRequest, Unit, UnitMembership

COORDINATION_SLUG = "coordination"

# Called with (unit) when a unit gets its second worker. P03.T03 adds the default council rules here.
SECOND_WORKER_HOOKS: list = []


class UnitError(ValueError):
    """A plain-words reason why something cannot be done."""


def coordination_unit():
    """The one system unit that holds Unicorn's own coordination work."""
    return Unit.objects.get(slug=COORDINATION_SLUG)


# --- Workers and the council ---


def workers(unit):
    return UnitMembership.objects.filter(unit=unit, left_at__isnull=True).select_related("member")


def council_members(unit):
    return workers(unit).filter(is_council=True)


def is_worker(member, unit) -> bool:
    return workers(unit).filter(member=member).exists()


def is_council_member(member, unit) -> bool:
    return council_members(unit).filter(member=member).exists()


def has_council(unit) -> bool:
    """HF-20: a unit with two or more workers has a working council."""
    return workers(unit).count() >= 2


def admission_rule(unit) -> str:
    """How new workers join. The unit's council rules decide (P03.T03); until then, the default."""
    from . import council_rules

    rules = council_rules.current(unit)
    return rules.admission if rules else get_param("governance.council.admission")


def _add_worker(unit, member):
    """Add an active worker. Caller holds the transaction."""
    membership = UnitMembership.objects.create(unit=unit, member=member, joined_at=timezone.now())
    audit.record(member.number, "unit.worker_joined", unit)
    if workers(unit).count() == 2:
        for hook in SECOND_WORKER_HOOKS:
            hook(unit)
    return membership


def add_first_worker(unit, member):
    """The first worker of a unit is its founder and its first responsible."""
    with transaction.atomic():
        membership = _add_worker(unit, member)
        if responsible(unit) is None:
            _start_responsibility(unit, member, "founder")
        return membership


def request_to_join(unit, member, message=""):
    if not member_services.is_verified(member):  # HF-13
        raise UnitError(_("Only verified members can join a unit."))
    if unit.status in ("closed", "closing", "merged"):
        raise UnitError(_("This unit is not taking new workers."))
    with transaction.atomic():
        if is_worker(member, unit):
            raise UnitError(_("You already work in this unit."))
        existing = JoinRequest.objects.filter(unit=unit, member=member, status="open").first()
        if existing:
            return existing
        request = JoinRequest.objects.create(unit=unit, member=member, message=message)
        audit.record(member.number, "unit.join_requested", unit)
        if admission_rule(unit) == "open":
            _accept(request, decider=None)
        return request


def _accept(request, decider):
    request.status = "accepted"
    request.decided_by = decider
    request.decided_at = timezone.now()
    request.save(update_fields=["status", "decided_by", "decided_at"])
    _add_worker(request.unit, request.member)


def can_decide_joins(member, unit) -> bool:
    """A council member, or the single worker of a one-person unit."""
    count = workers(unit).count()
    if count == 1:
        return is_worker(member, unit)
    return is_council_member(member, unit)


def decide_join(request, decider, accept):
    with transaction.atomic():
        request = JoinRequest.objects.select_for_update().get(pk=request.pk)
        if request.status != "open":
            raise UnitError(_("This request has already been decided."))
        if not member_services.is_verified(decider) or not can_decide_joins(decider, request.unit):
            raise UnitError(_("Only the unit's council can decide who joins."))
        if accept:
            if not member_services.is_verified(request.member):
                raise UnitError(_("Only verified members can join a unit."))
            _accept(request, decider)
        else:
            request.status = "declined"
            request.decided_by = decider
            request.decided_at = timezone.now()
            request.save(update_fields=["status", "decided_by", "decided_at"])
        audit.record(
            decider.number, "unit.join_decided", request.unit, accepted=bool(accept), member=request.member.number
        )
        return request


def leave_unit(member, unit):
    with transaction.atomic():
        membership = (
            UnitMembership.objects.select_for_update().filter(unit=unit, member=member, left_at__isnull=True).first()
        )
        if membership is None:
            raise UnitError(_("You do not work in this unit."))
        membership.left_at = timezone.now()
        membership.save()
        audit.record(member.number, "unit.worker_left", unit)
        current = responsible(unit)
        if current is not None and current.member_id == member.pk:
            _hand_over(unit, "handover", exclude={member.pk})


def _default_rules_hook(unit):
    from . import council_rules

    council_rules.create_default(unit)


SECOND_WORKER_HOOKS.append(_default_rules_hook)


# --- Council decisions ---

# kind -> function(decision) run when a decision of that kind is approved. P03.T06 adds close_unit.
DECISION_ACTIONS: dict = {}

# Functions called with (decision) when a decision is opened and when it is closed. The tickets app adds one of each,
# so that every council decision also has a ticket (P06.T07) and this app never imports it.
DECISION_OPENED_HOOKS: list = []
DECISION_CLOSED_HOOKS: list = []


def _apply_rules_change(decision):
    from . import council_rules

    council_rules.new_version(decision.unit, decision.payload, decision)


DECISION_ACTIONS["rules_change"] = _apply_rules_change


def open_decision(member, unit, title, text="", kind="other", payload=None):
    """A council member opens a decision. In a one-person unit there is nothing to vote on: it takes effect at once."""
    if not member_services.is_verified(member) or not can_decide_joins(member, unit):
        raise UnitError(_("Only the unit's council can open a decision."))
    return _create_decision(unit, member, title, text, kind, payload)


def open_system_decision(unit, title, text="", kind="other", payload=None):
    """A decision opened by the system for a unit's council, for example a suggestion from another part of the app."""
    return _create_decision(unit, None, title, text, kind, payload)


def _create_decision(unit, member, title, text, kind, payload):
    from datetime import timedelta

    from . import council_rules
    from .models import CouncilDecision

    rules = council_rules.current(unit)
    days = rules.vote_days if rules else get_param("governance.council.vote_days")
    now = timezone.now()
    with transaction.atomic():
        decision = CouncilDecision.objects.create(
            unit=unit,
            title=title,
            text=text,
            kind=kind,
            payload=payload or {},
            opened_by=member,
            opens_at=now,
            closes_at=now + timedelta(days=days),
        )
        audit.record(member.number if member else "system", "unit.decision_opened", decision, kind=kind)
        for hook in DECISION_OPENED_HOOKS:
            hook(decision)
        if not has_council(unit):
            _finish(decision, approved=True, result={"one_person_unit": True})
        return decision


def vote(decision, member, choice):
    from .models import CouncilVote

    if choice not in ("yes", "no", "abstain"):
        raise UnitError(_("Please answer yes, no or abstain."))
    with transaction.atomic():
        from .models import CouncilDecision

        decision = CouncilDecision.objects.select_for_update().get(pk=decision.pk)
        if decision.status != "open" or timezone.now() >= decision.closes_at:
            raise UnitError(_("This decision is closed."))
        if not member_services.is_verified(member) or not is_council_member(member, decision.unit):
            raise UnitError(_("Only council members can vote."))
        if CouncilVote.objects.filter(decision=decision, member=member).exists():
            raise UnitError(_("You have already voted."))
        CouncilVote.objects.create(decision=decision, member=member, vote=choice)
        audit.record(member.number, "unit.decision_voted", decision)
        council_ids = set(council_members(decision.unit).values_list("member_id", flat=True))
        voted = set(decision.votes.values_list("member_id", flat=True))
        if council_ids <= voted:
            tally(decision)
        return decision


def tally(decision):
    """Count the votes of the current council and close the decision. Safe to call twice."""
    from fractions import Fraction

    from . import council_rules
    from .models import CouncilDecision

    with transaction.atomic():
        decision = CouncilDecision.objects.select_for_update().get(pk=decision.pk)
        if decision.status != "open":
            return decision
        council_ids = set(council_members(decision.unit).values_list("member_id", flat=True))
        votes = [v.vote for v in decision.votes.all() if v.member_id in council_ids]
        yes, no, abstain = votes.count("yes"), votes.count("no"), votes.count("abstain")
        rules = council_rules.current(decision.unit)
        rule = rules.decision_rule if rules else get_param("governance.council.decision_rule")
        quorum = rules.quorum if rules else get_param("governance.council.quorum")
        result = {"yes": yes, "no": no, "abstain": abstain, "council_size": len(council_ids), "rule": rule}
        if len(votes) < quorum * len(council_ids) or not votes:
            approved, result["reason"] = False, "quorum"
        elif rule == "majority":
            approved = yes > no
        elif rule == "two_thirds":
            approved = yes + no > 0 and Fraction(yes, yes + no) >= Fraction(2, 3)
        else:
            approved = no == 0 and yes >= 1
        return _finish(decision, approved, result)


def _finish(decision, approved, result):
    decision.status = "approved" if approved else "rejected"
    decision.result = result
    decision.save(update_fields=["status", "result"])
    audit.record("system", "unit.decision_closed", decision, status=decision.status)
    if approved and decision.kind in DECISION_ACTIONS:
        DECISION_ACTIONS[decision.kind](decision)
    for hook in DECISION_CLOSED_HOOKS:
        hook(decision)
    return decision


def close_due_decisions(now=None):
    from .models import CouncilDecision

    count = 0
    for d in CouncilDecision.objects.filter(status="open", closes_at__lte=now or timezone.now()):
        tally(d)
        count += 1
    return count


# --- The responsible and rotation ---


def responsible(unit):
    """The current Responsibility row, or None."""
    from .models import Responsibility

    return Responsibility.objects.filter(unit=unit, ends_at__isnull=True).select_related("member").first()


def can_edit_unit(member, unit) -> bool:
    """The unit's profile, offers and recipes: the responsible, or any council member (the default)."""
    current = responsible(unit)
    if current is not None and current.member_id == member.pk:
        return True
    return is_council_member(member, unit) or (workers(unit).count() == 1 and is_worker(member, unit))


def _start_responsibility(unit, member, how, declined_by=None):
    from .models import Responsibility

    row = Responsibility.objects.create(
        unit=unit, member=member, starts_at=timezone.now(), how=how, declined_by=declined_by or []
    )
    audit.record(member.number, "unit.responsible_started", unit, how=how)
    return row


def days_responsible(unit, member, now=None) -> int:
    from .models import Responsibility

    now = now or timezone.now()
    total = 0
    for r in Responsibility.objects.filter(unit=unit, member=member):
        total += ((r.ends_at or now) - r.starts_at).days
    return total


def _next_responsible(unit, exclude):
    """The active council member with the fewest days as responsible; ties go to the earliest joined."""
    candidates = [m for m in council_members(unit) if m.member_id not in exclude]
    if not candidates:
        return None
    candidates.sort(key=lambda m: (days_responsible(unit, m.member), m.joined_at, m.pk))
    return candidates[0].member


def _notify(member, subject, body):
    from django.core import mail

    audit.record("system", "notice.sent", member, subject=subject)
    if not member.deleted and member.status == "member":
        mail.send_mail(subject, body, None, [member.user.email])


def _hand_over(unit, how, exclude, declined_by=None):
    """End the current responsibility and start the next one. Caller holds the transaction."""
    current = responsible(unit)
    if current is not None:
        current.ends_at = timezone.now()
        current.save(update_fields=["ends_at"])
    skip = set(exclude) | set(declined_by or [])
    chosen = _next_responsible(unit, skip)
    if chosen is None:
        return None
    row = _start_responsibility(unit, chosen, how, declined_by=declined_by)
    _notify(
        chosen,
        _("You are now the responsible of %(unit)s") % {"unit": unit.name},
        _("The responsibility of %(unit)s has passed to you. You can decline it on the unit page.")
        % {"unit": unit.name},
    )
    if current is not None and current.member_id != chosen.pk:
        _notify(
            current.member,
            _("Your turn as responsible of %(unit)s has ended") % {"unit": unit.name},
            _("Thank you. The responsibility has passed to the next worker."),
        )
    return row


def rotate_due(now=None):
    """Pass the responsibility on in every council unit whose turn is older than its rotation time."""
    from . import council_rules
    from .models import Responsibility

    now = now or timezone.now()
    count = 0
    for current in Responsibility.objects.filter(ends_at__isnull=True).select_related("unit"):
        unit = current.unit
        if unit.status in ("closed", "merged") or not has_council(unit):
            continue
        rules = council_rules.current(unit)
        months = rules.rotation_months if rules else get_param("governance.council.rotation_months")
        if member_services._add_months(current.starts_at, months) > now:
            continue
        with transaction.atomic():
            current = Responsibility.objects.select_for_update().get(pk=current.pk)
            if current.ends_at is not None:
                continue
            if _hand_over(unit, "rotation", exclude={current.member_id}) is not None:
                count += 1
    return count


def decline_turn(member, unit):
    """The responsible declines; the next worker is chosen at once."""
    with transaction.atomic():
        current = responsible(unit)
        if current is None or current.member_id != member.pk:
            raise UnitError(_("You are not the responsible of this unit."))
        declined = list(current.declined_by) + [member.pk]
        row = _hand_over(unit, "rotation", exclude={member.pk}, declined_by=declined)
        if row is None:
            # everybody declined: the turn starts again with the one who has held it least
            row = _hand_over(unit, "rotation", exclude=set())
        audit.record(member.number, "unit.turn_declined", unit)
        return row


def _leave_check(member):
    """Leaving Unicorn hands over every responsibility at once instead of blocking."""
    from .models import Responsibility

    for r in Responsibility.objects.filter(member=member, ends_at__isnull=True).select_related("unit"):
        _hand_over(r.unit, "handover", exclude={member.pk})
    for m in UnitMembership.objects.filter(member=member, left_at__isnull=True):
        m.left_at = timezone.now()
        m.save()
    return []


if _leave_check not in member_services.LEAVE_CHECKS:
    member_services.LEAVE_CHECKS.append(_leave_check)


# --- Opening, ending trials, going dormant, closing ---

CLOSE_CHECKS: list = []  # check(unit) -> list[str] of plain-words reasons; P05 adds open production orders


def _slug_for(name):
    from django.utils.text import slugify

    base = slugify(name)[:70] or "unit"
    if base in RESERVED_SLUGS:
        base = f"{base}-unit"
    slug, n = base, 2
    while Unit.objects.filter(slug=slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


RESERVED_SLUGS = {"open", "requests", "decisions", "me"}


def open_unit(member, data):
    """Open a unit. Hard-frame checks block (HF-13, HF-17); the plan check never refuses (HF-15)."""
    from datetime import timedelta  # noqa: F401

    from apps.plan import check as plan_check

    from . import council_rules  # noqa: F401

    if not member_services.is_verified(member):  # HF-13
        raise UnitError(_("Only verified members can open a unit."))
    kind = data.get("kind")
    licence = data.get("licence_kind_required", "")
    if licence and not member_services.has_verified_licence(member, licence):  # HF-17
        raise UnitError(
            _("This trade needs a licence by law. Add your licence to your portfolio and wait until it is verified.")
        )
    if kind in ("service", "social") and not data.get("insurance_confirmed"):  # HF-17
        raise UnitError(_("A service needs insurance. Please confirm that the unit is insured."))
    result = plan_check.check(
        {"type": "open_unit", "kind": kind, "name": data.get("name", ""), "member": member.number}
    )
    now = timezone.now()
    fields = {
        k: data[k]
        for k in (
            "name",
            "kind",
            "mode",
            "description",
            "trade_code",
            "town",
            "postcode",
            "country",
            "cover_radius_km",
            "licence_kind_required",
            "insurance_confirmed",
        )
        if k in data
    }
    with transaction.atomic():
        unit = Unit(slug=_slug_for(data["name"]), created_by=member, last_activity_at=now, **fields)
        if result.color == "red":
            unit.status = "paused"
            unit.status_note = _("waiting for random confirmers")  # HF-15: a ticket, never a refusal
        else:
            unit.status = "trial"
            unit.opened_at = now
            unit.trial_until = member_services._add_months(now, get_param("governance.units.trial_months"))
        unit.save()
        add_first_worker(unit, member)
        audit.record(
            member.number,
            "unit.opened",
            unit,
            check=result.color,
            points=[{"color": p.color, "text": p.text} for p in result.points],
        )
        if result.color == "red":
            from apps.tickets import briefs

            briefs.open_unit(unit, member, result)  # HF-15: the random confirmers decide before it opens
        return unit


def end_trials(now=None):
    now = now or timezone.now()
    count = 0
    for unit in Unit.objects.filter(status="trial", trial_until__lte=now):
        unit.status = "open"
        unit.save(update_fields=["status"])
        audit.record("system", "unit.trial_ended", unit)
        count += 1
    return count


def mark_dormant(now=None):
    """Open units with no activity for `dormant_after_months` become dormant."""
    now = now or timezone.now()
    cutoff = member_services._add_months(now, -get_param("governance.units.dormant_after_months"))
    count = 0
    for unit in Unit.objects.filter(status="open").exclude(kind="coordination"):
        last = unit.last_activity_at or unit.opened_at
        if last is not None and last < cutoff:
            unit.status = "dormant"
            unit.save(update_fields=["status"])
            audit.record("system", "unit.dormant", unit)
            count += 1
    return count


def reopen_unit(member, unit):
    if not is_worker(member, unit):
        raise UnitError(_("Only workers of the unit can reopen it."))
    if unit.status != "dormant":
        raise UnitError(_("This unit is not dormant."))
    unit.status = "open"
    unit.last_activity_at = timezone.now()
    unit.save(update_fields=["status", "last_activity_at"])
    audit.record(member.number, "unit.reopened", unit)
    return unit


def release_unit(unit):
    """A paused unit starts its trial: its opening was approved."""
    with transaction.atomic():
        unit = Unit.objects.select_for_update().get(pk=unit.pk)
        if unit.status != "paused":
            return unit
        now = timezone.now()
        unit.status, unit.status_note, unit.opened_at = "trial", "", now
        unit.trial_until = member_services._add_months(now, get_param("governance.units.trial_months"))
        unit.save(update_fields=["status", "status_note", "opened_at", "trial_until"])
        audit.record("system", "unit.released", unit)
        return unit


# Functions called with (unit) when a unit is paused by a decision; the market releases its open orders (P06.T10).
PAUSE_HOOKS: list = []


def pause_unit(unit, reason):
    """Pause a unit after a panel said it should not keep working. Its open orders are released."""
    with transaction.atomic():
        unit = Unit.objects.select_for_update().get(pk=unit.pk)
        if unit.status in ("closed", "merged", "paused"):
            return unit
        unit.status, unit.status_note = "paused", str(reason)[:120]
        unit.save(update_fields=["status", "status_note"])
        audit.record("system", "unit.paused", unit, reason=str(reason))
        for hook in PAUSE_HOOKS:
            hook(unit)
        return unit


def touch(unit):
    """Record that something happened in the unit (hours, orders, bookings)."""
    Unit.objects.filter(pk=unit.pk).update(last_activity_at=timezone.now())


def close_unit(unit, reason, member=None, decision=None, ticket=None):
    """Close a unit: by an approved council decision or ticket, or by the single worker of a one-person unit.

    Returns the list of reasons that still block closing (the unit stays `closing`), or [] when it is closed.
    """
    if not (reason or "").strip():
        raise UnitError(_("Please write why the unit is closing."))
    with transaction.atomic():
        unit = Unit.objects.select_for_update().get(pk=unit.pk)
        by_decision = decision is not None and decision.unit_id == unit.pk and decision.status == "approved"
        alone = (
            member is not None
            and workers(unit).count() == 1
            and is_worker(member, unit)
            and member_services.is_verified(member)
        )
        by_ticket = ticket is not None and ticket.status == "approved"
        if not (by_decision or alone or by_ticket):
            raise UnitError(_("Closing a unit needs a decision of its council."))
        if unit.status in ("closed", "merged"):
            return []
        blockers = [r for check in CLOSE_CHECKS for r in check(unit)]
        if blockers:
            unit.status = "closing"
            unit.save(update_fields=["status"])
            audit.record("system", "unit.closing", unit, reason=reason, blockers=blockers)
            return blockers
        unit.status = "closed"
        unit.closed_at = timezone.now()
        unit.save(update_fields=["status", "closed_at"])
        audit.record("system", "unit.closed", unit, reason=reason)
        return []


DECISION_ACTIONS["close_unit"] = lambda decision: close_unit(
    decision.unit, decision.text or decision.title, decision=decision
)


# --- Recording hours ---

BERLIN = ZoneInfo("Europe/Berlin")


def period_for_date(day):
    """The ledger period (calendar month, Europe/Berlin) that contains `day`."""
    from datetime import datetime, time

    from apps.ledger.services import current_period

    return current_period(datetime.combine(day, time(12, 0), tzinfo=BERLIN))


def _week_minutes(member, day, exclude=None):
    from datetime import timedelta

    from django.db.models import Sum

    from .models import HoursEntry

    monday = day - timedelta(days=day.weekday())
    rows = HoursEntry.objects.filter(
        member=member, date__range=(monday, monday + timedelta(days=6)), status__in=COUNTED_STATUSES
    )
    if exclude is not None:
        rows = rows.exclude(pk=exclude)
    return rows.aggregate(t=Sum("minutes"))["t"] or 0


COUNTED_STATUSES = ("submitted", "approved", "pending_sale", "paid")


def create_draft(member, unit, date, minutes, activity="other", note="", ref_type="", ref_id=""):
    from .models import HoursEntry

    if not isinstance(minutes, int) or not 1 <= minutes <= 1440:
        raise UnitError(_("Please enter between 1 minute and 24 hours."))
    if activity not in dict(HoursEntry.ACTIVITIES):
        raise UnitError(_("Please choose what kind of work it was."))
    return HoursEntry.objects.create(
        member=member,
        unit=unit,
        date=date,
        minutes=minutes,
        activity=activity,
        note=note[:300],
        ref_type=ref_type,
        ref_id=str(ref_id),
    )


def submit_hours(entry):
    """Send a draft for approval. Checks the worker, the date, the period and the weekly limit."""
    from .models import HoursEntry

    with transaction.atomic():
        entry = HoursEntry.objects.select_for_update().get(pk=entry.pk)
        if entry.status != "draft":
            raise UnitError(_("These hours were already sent."))
        if entry.unit.kind != "coordination" and not is_worker(entry.member, entry.unit):
            raise UnitError(_("You can only record hours for a unit you work in."))
        if entry.date > timezone.now().astimezone(BERLIN).date():
            raise UnitError(_("You cannot record hours for a day that has not happened yet."))
        period = period_for_date(entry.date)
        if period.status != "open":
            raise UnitError(_("That month is already closed, so hours can no longer be added to it."))
        limit = int(get_param("membership.max_unicorn_hours_per_week") * 60)
        entry.needs_extra_approval = _week_minutes(entry.member, entry.date, exclude=entry.pk) + entry.minutes > limit
        entry.period = period
        entry.status = "submitted"
        entry.submitted_at = timezone.now()
        entry.save()
        touch(entry.unit)
        audit.record(entry.member.number, "hours.submitted", entry, minutes=entry.minutes, unit=entry.unit_id)
        if _approved_by_system(entry.unit):
            approve_hours(entry)
            entry.refresh_from_db()
        return entry


def record_hours(member, unit, date, minutes, **kw):
    return submit_hours(create_draft(member, unit, date, minutes, **kw))


def record_coordination(member, minutes, note, ref_type="", ref_id=""):
    """Governance work (reviews, panels, mediation, tasks): hours of the coordination unit, approved by the system.

    Anyone may do it, so the member need not be a worker of that unit (docs/05 section 1 item 4).
    """
    today = timezone.now().astimezone(BERLIN).date()
    return record_hours(
        member,
        coordination_unit(),
        today,
        minutes,
        activity="coordination",
        note=note,
        ref_type=ref_type,
        ref_id=ref_id,
    )


def start_timer(member, unit):
    from .models import TimerSession

    if not is_worker(member, unit):
        raise UnitError(_("You can only record hours for a unit you work in."))
    with transaction.atomic():
        if TimerSession.objects.filter(member=member).exists():
            raise UnitError(_("Your timer is already running."))
        return TimerSession.objects.create(member=member, unit=unit, started_at=timezone.now())


def stop_timer(member, now=None):
    """Stop the timer and make a draft entry with the minutes rounded to the nearest minute (at least one)."""
    from .models import TimerSession

    now = now or timezone.now()
    with transaction.atomic():
        timer = TimerSession.objects.select_for_update().filter(member=member).first()
        if timer is None:
            raise UnitError(_("Your timer is not running."))
        minutes = max(1, min(1440, round((now - timer.started_at).total_seconds() / 60)))
        day = timer.started_at.astimezone(BERLIN).date()
        entry = create_draft(member, timer.unit, day, minutes, note=_("Recorded with the timer"))
        timer.delete()
        return entry


# --- Approving and paying hours (HF-20) ---


def _approved_by_system(unit) -> bool:
    return unit.kind == "coordination" or workers(unit).count() == 1


def _approvals_needed(entry, approvals) -> bool:
    """True when the approvals so far are enough under the council's rules."""
    from . import council_rules

    rules = council_rules.current(entry.unit)
    rule = rules.hours_approval if rules else get_param("governance.council.hours_approval")
    count = len(approvals)
    if entry.needs_extra_approval:
        return count >= 2 and all(a.reason.strip() for a in approvals)
    if rule == "any_other_member":
        return count >= 1
    if rule == "two_members":
        return count >= 2
    boss = responsible(entry.unit)  # responsible_or_other
    if boss is not None and any(a.approver_id == boss.member_id for a in approvals):
        return True
    return count >= 2


def approve_hours(entry, approver=None, reason=""):
    """Record an approval; pay when enough approvals exist. Never lets a member approve their own hours (HF-20)."""
    from .models import HoursApproval, HoursEntry

    with transaction.atomic():
        entry = HoursEntry.objects.select_for_update().get(pk=entry.pk)
        if entry.status != "submitted":
            raise UnitError(_("These hours are not waiting for approval."))
        unit = entry.unit
        if approver is None:
            if not _approved_by_system(unit):
                raise UnitError(_("The unit's council must approve these hours."))
            if entry.needs_extra_approval:
                # OWNER-CHECK: a one-person unit has no council to approve hours over the weekly limit.
                return entry
            HoursApproval.objects.create(entry=entry, approver=None, approved_at=timezone.now())
            return _finish_approval(entry)
        if approver.pk == entry.member_id:
            raise UnitError(_("You cannot approve your own hours."))
        if not member_services.is_verified(approver) or not is_council_member(approver, unit):
            raise UnitError(_("Only council members of the unit can approve its hours."))
        if _approved_by_system(unit):
            raise UnitError(_("These hours are approved automatically."))
        if entry.approvals.filter(approver=approver).exists():
            raise UnitError(_("You have already approved these hours."))
        if entry.needs_extra_approval and not reason.strip():
            raise UnitError(_("These hours are over the weekly limit. Please write a reason to approve them."))
        HoursApproval.objects.create(
            entry=entry, approver=approver, approved_at=timezone.now(), reason=reason.strip()[:300]
        )
        audit.record(approver.number, "hours.approved", entry)
        if _approvals_needed(entry, list(entry.approvals.all())):
            return _finish_approval(entry)
        return entry


def _finish_approval(entry):
    entry.status = "approved"
    entry.save(update_fields=["status"])
    if entry.activity == "own_initiative":
        entry.status = "pending_sale"  # paid in P05 when the products sell
        entry.save(update_fields=["status"])
        return entry
    return pay_hours(entry)


def _hm(minutes):
    return f"{minutes // 60}:{minutes % 60:02d}"


def pay_hours(entry):
    """Pay approved hours: gross from Fund 2, then the flat tax back to Fund 2 (HF-1, HF-2, HF-9)."""
    from decimal import Decimal

    from apps.core.money import minutes_to_uniq, uniq
    from apps.ledger import services as ledger

    from .models import HoursEntry

    with transaction.atomic():
        entry = HoursEntry.objects.select_for_update().get(pk=entry.pk)
        if entry.transaction_id or entry.status not in ("approved", "pending_sale"):
            raise UnitError(_("These hours cannot be paid now."))
        if not entry.approvals.exists():  # HF-20: no approval, no payment
            raise UnitError(_("Hours are only paid after they are approved."))
        assert not get_param("economy.shortage_bonus.enabled")  # the bonus is built in phase 16
        gross = uniq(minutes_to_uniq(entry.minutes) * Decimal(str(get_param("economy.uniq_per_hour"))))
        account = ledger.member_account(entry.member)
        period = entry.period
        tx = ledger.post(
            "hours_pay",
            _("Paid for %(time)s at %(unit)s on %(date)s")
            % {"time": _hm(entry.minutes), "unit": entry.unit.name, "date": entry.date.isoformat()},
            [ledger.Leg(ledger.fund2(), -gross), ledger.Leg(account, gross)],
            ref=entry,
            period=period,
        )
        tax = uniq(gross * period.tax_rate)
        if tax:
            ledger.post(
                "tax",
                _("Flat tax %(rate)s%%") % {"rate": (period.tax_rate * 100).normalize()},
                [ledger.Leg(account, -tax), ledger.Leg(ledger.fund2(), tax)],
                ref=entry,
                period=period,
            )
        entry.transaction = tx
        entry.status = "paid"
        entry.save(update_fields=["transaction", "status"])
        audit.record("system", "hours.paid", entry, gross=str(gross), tax=str(tax))
        return entry


def reject_hours(entry, approver, reason):
    from .models import HoursEntry

    if not (reason or "").strip():
        raise UnitError(_("Please write why you are rejecting these hours."))
    with transaction.atomic():
        entry = HoursEntry.objects.select_for_update().get(pk=entry.pk)
        if entry.status != "submitted":
            raise UnitError(_("These hours are not waiting for approval."))
        if approver.pk == entry.member_id or not is_council_member(approver, entry.unit):
            raise UnitError(_("Only other council members of the unit can reject its hours."))
        entry.status = "rejected"
        entry.rejection_reason = reason.strip()[:300]
        entry.save(update_fields=["status", "rejection_reason"])
        audit.record(approver.number, "hours.rejected", entry)
        _notify(
            entry.member,
            _("Your hours at %(unit)s were not approved") % {"unit": entry.unit.name},
            _("Reason: %(reason)s") % {"reason": entry.rejection_reason},
        )
        return entry


def correct_hours(entry, minutes, reason):
    """Pay again after a mistake: reverse the payment and the tax with written reasons, then pay the right amount.

    Used by an approved `hours_correct` ticket. Ledger rows are never changed; the correction is new rows (HF-7).
    """
    from apps.ledger import services as ledger
    from apps.ledger.models import Transaction

    from .models import HoursEntry

    if not (reason or "").strip():
        raise UnitError(_("A correction needs a written reason."))
    if not isinstance(minutes, int) or not 0 <= minutes <= 1440:
        raise UnitError(_("Please enter between 0 minutes and 24 hours."))
    with transaction.atomic():
        entry = HoursEntry.objects.select_for_update().get(pk=entry.pk)
        if entry.status != "paid" or entry.transaction_id is None:
            raise UnitError(_("Only paid hours can be corrected."))
        taxes = list(Transaction.objects.filter(kind="tax", ref_type="hoursentry", ref_id=str(entry.pk)))
        for tx in [*taxes, entry.transaction]:  # the tax first: the member holds only what is left after it
            legs = [ledger.Leg(e.account, -e.amount) for e in tx.entries.select_related("account")]
            ledger.post("correction", reason, legs, ref=tx)
        entry.transaction = None
        if minutes == 0:
            entry.status, entry.rejection_reason = "rejected", str(reason)[:300]
            entry.save(update_fields=["transaction", "status", "rejection_reason"])
        else:
            entry.minutes, entry.status, entry.period = minutes, "approved", ledger.current_period()
            entry.save(update_fields=["transaction", "minutes", "status", "period"])
            pay_hours(entry)
        audit.record("system", "hours.corrected", entry, minutes=minutes, reason=reason)
        return entry


def waiting_for(member, unit):
    """Submitted hours of the unit that this council member may approve."""
    from .models import HoursEntry

    if not is_council_member(member, unit):
        return HoursEntry.objects.none()
    return (
        HoursEntry.objects.filter(unit=unit, status="submitted")
        .exclude(member=member)
        .exclude(approvals__approver=member)
        .select_related("member")
    )


# --- Reports ---


def month_bounds(year, month):
    from datetime import date, timedelta

    first = date(year, month, 1)
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    return first, nxt - timedelta(days=1)


def unit_report(unit, year, month):
    """Hours of the unit in a month by worker, by activity and by status (drafts left out)."""
    from collections import defaultdict

    from .models import HoursEntry

    first, last = month_bounds(year, month)
    rows = HoursEntry.objects.filter(unit=unit, date__range=(first, last)).exclude(status="draft")
    rows = rows.select_related("member")
    by_worker, by_activity, by_status = defaultdict(int), defaultdict(int), defaultdict(int)
    for e in rows:
        by_worker[e.member.display_name] += e.minutes
        by_activity[e.get_activity_display()] += e.minutes
        by_status[e.get_status_display()] += e.minutes
    return {
        "by_worker": sorted(by_worker.items()),
        "by_activity": sorted(by_activity.items()),
        "by_status": sorted(by_status.items()),
        "total": sum(by_worker.values()),
    }


def my_hours_totals(member):
    """Per month and per unit: paid minutes, gross UNIQ, tax and net."""
    from collections import defaultdict
    from decimal import Decimal

    from apps.core.money import minutes_to_uniq, uniq

    from .models import HoursEntry

    by_month, by_unit = (
        defaultdict(lambda: [0, Decimal(0), Decimal(0)]),
        defaultdict(lambda: [0, Decimal(0), Decimal(0)]),
    )
    for e in HoursEntry.objects.filter(member=member, status="paid").select_related("unit", "period"):
        gross = minutes_to_uniq(e.minutes)
        tax = uniq(gross * e.period.tax_rate)
        for bucket in (by_month[f"{e.period.year}-{e.period.month:02d}"], by_unit[e.unit.name]):
            bucket[0] += e.minutes
            bucket[1] += gross
            bucket[2] += tax
    fmt = lambda d: [(k, v[0], v[1], v[2], v[1] - v[2]) for k, v in sorted(d.items(), reverse=True)]  # noqa: E731
    return fmt(by_month), fmt(by_unit)


def public_numbers(unit, months=12):
    """Approved hours per month and the number of workers: no names."""
    from django.db.models import Sum
    from django.db.models.functions import TruncMonth

    from .models import HoursEntry

    rows = (
        HoursEntry.objects.filter(unit=unit, status__in=["approved", "paid", "pending_sale"])
        .annotate(m=TruncMonth("date"))
        .values("m")
        .annotate(total=Sum("minutes"))
        .order_by("-m")[:months]
    )
    return [(r["m"].strftime("%Y-%m"), r["total"]) for r in rows], workers(unit).count()
