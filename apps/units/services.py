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


def _apply_rules_change(decision):
    from . import council_rules

    council_rules.new_version(decision.unit, decision.payload, decision)


DECISION_ACTIONS["rules_change"] = _apply_rules_change


def open_decision(member, unit, title, text="", kind="other", payload=None):
    """A council member opens a decision. In a one-person unit there is nothing to vote on: it takes effect at once."""
    from datetime import timedelta

    from . import council_rules
    from .models import CouncilDecision

    if not member_services.is_verified(member) or not can_decide_joins(member, unit):
        raise UnitError(_("Only the unit's council can open a decision."))
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
        audit.record(member.number, "unit.decision_opened", decision, kind=kind)
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
