"""Unions: forming, joining and leaving (docs/05 section 7). A union advises and never commands (HF-15, HF-20)."""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.notify import notify
from apps.core.rotation import next_in_rotation
from apps.core.tally import count
from apps.members import services as member_services
from apps.rules.services import get_param
from apps.tickets import services as ticket_services
from apps.units import services as unit_services

from .models import Union, UnionDecision, UnionDelegate, UnionMembership, UnionRules, UnionVote

FORMING_DAYS = 90


class BodyError(ValueError):
    """A plain-words reason why something cannot be done."""


# --- Who is in a union ---


def member_units(union):
    """The units that belong to the union now and are still working."""
    from apps.units.models import Unit

    ids = UnionMembership.objects.filter(union=union, left_at__isnull=True).values("unit_id")
    return Unit.objects.filter(pk__in=ids).exclude(status__in=["closed", "merged"])


def is_member_unit(union, unit) -> bool:
    return member_units(union).filter(pk=unit.pk).exists()


def unions_of(unit):
    ids = UnionMembership.objects.filter(unit=unit, left_at__isnull=True).values("union_id")
    return Union.objects.filter(pk__in=ids).exclude(status="dissolved")


def current_rules(union):
    return union.rules.order_by("-version").first()


def can_act_for(member, union) -> bool:
    """A verified member who can speak for one of the union's units (or the unit that formed it)."""
    if member is None or not member_services.is_verified(member):
        return False
    units = list(member_units(union))
    if not units:
        units = [union.created_by_unit]
    return any(unit_services.can_edit_unit(member, u) for u in units)


def _unit_responsible_member(unit):
    row = unit_services.responsible(unit)
    if row is not None:
        return row.member
    first = unit_services.workers(unit).order_by("joined_at").first()
    return first.member if first else None


# --- Forming ---


def _create_rules(union, version=1):
    return UnionRules.objects.create(
        union=union,
        version=version,
        decision_rule=get_param("governance.council.decision_rule"),
        quorum=get_param("governance.council.quorum"),
        vote_days=get_param("governance.council.vote_days"),
        rotation_months=get_param("governance.unions.delegate_rotation_months"),
        adopted_at=timezone.now(),
    )


def _unique_slug(name):
    base = slugify(name)[:70] or "union"
    slug, n = base, 2
    while Union.objects.filter(slug=slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


def _join_ticket(union, unit, author, open_now=True):
    return ticket_services.create_ticket(
        "union_join",
        author,
        _("%(unit)s joins the union %(union)s") % {"unit": unit.name, "union": union.name},
        _("The council of %(unit)s decides whether the unit joins %(union)s.")
        % {"unit": unit.name, "union": union.name},
        scope="unit",
        scope_unit=unit,
        action_payload={"union_id": union.pk, "unit_id": unit.pk},
        open_now=open_now,
    )


def form_union(member, unit, name, trade_codes, description=""):
    """A unit's responsible forms a union. It is `forming` until the unit's council agrees and enough units join."""
    name = (name or "").strip()
    codes = [c.strip() for c in trade_codes if c and c.strip()]
    if not name:
        raise BodyError(_("Please give the union a name."))
    if not codes:
        raise BodyError(_("Please name at least one trade the union is about."))
    if not member_services.is_verified(member) or not unit_services.can_edit_unit(member, unit):
        raise BodyError(_("Only the responsible of a unit can form a union for it."))
    if unit.status in ("closed", "merged"):
        raise BodyError(_("This unit is closed."))
    if Union.objects.filter(name__iexact=name).exists():
        raise BodyError(_("There is already a union with this name."))
    with transaction.atomic():
        union = Union.objects.create(
            name=name,
            slug=_unique_slug(name),
            trade_codes=codes,
            description=description,
            created_by_unit=unit,
            forming_since=timezone.now(),
        )
        _create_rules(union)
        audit.record(member.number, "union.formed", union, unit=unit.slug)
        _join_ticket(union, unit, member)
        return union


def _refresh_status(union):
    """A union with enough units is active; with fewer it is forming again, and its 90 days start over."""
    enough = member_units(union).count() >= get_param("governance.unions.min_councils")
    if enough and union.status != "active":
        union.status, union.forming_since = "active", None
        union.save(update_fields=["status", "forming_since"])
        audit.record("system", "union.activated", union)
    elif not enough and union.status == "active":
        union.status, union.forming_since = "forming", timezone.now()
        union.save(update_fields=["status", "forming_since"])
        audit.record("system", "union.forming_again", union)


def add_unit(union, unit, ticket=None):
    """Put a unit into the union. Safe to call twice."""
    with transaction.atomic():
        union = Union.objects.select_for_update().get(pk=union.pk)
        if union.status == "dissolved":
            raise BodyError(_("This union was dissolved."))
        if UnionMembership.objects.filter(union=union, unit=unit, left_at__isnull=True).exists():
            return union
        UnionMembership.objects.create(union=union, unit=unit, joined_at=timezone.now(), ticket=ticket)
        audit.record("system", "union.unit_joined", union, unit=unit.slug)
        _refresh_status(union)
        for hook in UNIT_JOINED_HOOKS:
            hook(union, unit)
        return union


def remove_unit(union, unit):
    with transaction.atomic():
        union = Union.objects.select_for_update().get(pk=union.pk)
        rows = UnionMembership.objects.filter(union=union, unit=unit, left_at__isnull=True)
        if not rows.exists():
            return union
        rows.update(left_at=timezone.now())
        audit.record("system", "union.unit_left", union, unit=unit.slug)
        for hook in UNIT_LEFT_HOOKS:
            hook(union, unit)
        _refresh_status(union)
        return union


# Called with (union, unit) after a unit joined or left. The delegates (P13.T03) hook in here.
UNIT_JOINED_HOOKS: list = []
UNIT_LEFT_HOOKS: list = []


# --- Inviting, joining, leaving ---


def invite_unit(member, union, unit):
    """A member of the union invites another unit. Its responsible gets a draft ticket to open or withdraw."""
    if not can_act_for(member, union):
        raise BodyError(_("Only members who speak for a unit of this union can invite another unit."))
    if union.status == "dissolved":
        raise BodyError(_("This union was dissolved."))
    if is_member_unit(union, unit):
        raise BodyError(_("This unit is already in the union."))
    invited = _unit_responsible_member(unit)
    if invited is None:
        raise BodyError(_("This unit has nobody who could answer."))
    with transaction.atomic():
        ticket = _join_ticket(union, unit, invited, open_now=False)
        audit.record(member.number, "union.invited", union, unit=unit.slug, ticket=ticket.number)
        notify(
            invited,
            _("%(union)s invites %(unit)s to join. Open the request when your council wants to decide.")
            % {"union": union.name, "unit": unit.name},
            f"/tickets/{ticket.number}/",
            email=True,
        )
        return ticket


def accept_invitation(ticket, member):
    """The invited unit's responsible opens the draft ticket, and the unit's council decides."""
    if ticket.type != "union_join" or ticket.status != "draft" or ticket.author_id != member.pk:
        raise BodyError(_("This invitation is not yours to answer."))
    return ticket_services.open_ticket(ticket)


def decline_invitation(ticket, member):
    if ticket.type != "union_join" or ticket.status != "draft" or ticket.author_id != member.pk:
        raise BodyError(_("This invitation is not yours to answer."))
    ticket_services.set_status(ticket, "withdrawn", _("The unit declined the invitation."))
    return ticket


def leave_union(member, union, unit):
    """The unit's council decides to leave. A one-person unit decides at once."""
    if not member_services.is_verified(member) or not unit_services.can_edit_unit(member, unit):
        raise BodyError(_("Only the responsible of a unit can ask to leave a union."))
    if not is_member_unit(union, unit):
        raise BodyError(_("This unit is not in the union."))
    return ticket_services.create_ticket(
        "union_leave",
        member,
        _("%(unit)s leaves the union %(union)s") % {"unit": unit.name, "union": union.name},
        _("The council of %(unit)s decides whether the unit leaves %(union)s.")
        % {"unit": unit.name, "union": union.name},
        scope="unit",
        scope_unit=unit,
        action_payload={"union_id": union.pk, "unit_id": unit.pk},
    )


def dissolve_forming(now=None) -> int:
    """A union that stayed `forming` for 90 days is dissolved. Safe to run twice."""
    now = now or timezone.now()
    count = 0
    for union in Union.objects.filter(status="forming", forming_since__lte=now - timedelta(days=FORMING_DAYS)):
        with transaction.atomic():
            union = Union.objects.select_for_update().get(pk=union.pk)
            if union.status != "forming":
                continue
            for unit in list(member_units(union)):
                remove_unit(union, unit)
            union.status, union.forming_since = "dissolved", None
            union.save(update_fields=["status", "forming_since"])
            audit.record("system", "union.dissolved", union, reason="too small for 90 days")
            count += 1
    return count


# --- Delegates (P13.T03) ---


def current_delegate(union, unit):
    """The delegate row of a unit, or None. A delegate who no longer works in the unit does not count."""
    row = UnionDelegate.objects.filter(union=union, unit=unit, ends_at__isnull=True).select_related("member").first()
    if row is not None and not unit_services.is_worker(row.member, unit):
        return None
    return row


def current_delegates(union):
    """The current delegates of the union's member units, one per unit."""
    unit_ids = list(member_units(union).values_list("pk", flat=True))
    rows = UnionDelegate.objects.filter(union=union, unit_id__in=unit_ids, ends_at__isnull=True)
    return [r for r in rows.select_related("member", "unit") if unit_services.is_worker(r.member, r.unit)]


def delegate_for(member, union):
    """The row that makes `member` a delegate of the union, or None."""
    for row in current_delegates(union):
        if row.member_id == member.pk:
            return row
    return None


def days_as_delegate(union, unit, member, now=None) -> int:
    now = now or timezone.now()
    rows = UnionDelegate.objects.filter(union=union, unit=unit, member=member)
    return sum(((r.ends_at or now) - r.starts_at).days for r in rows)


def _pick_delegate(union, unit, exclude):
    candidates = [(m.member, m.joined_at) for m in unit_services.council_members(unit)]
    return next_in_rotation(candidates, lambda m: days_as_delegate(union, unit, m), exclude)


def _start_delegate(union, unit, member, how, declined_by=None):
    row = UnionDelegate.objects.create(
        union=union, unit=unit, member=member, starts_at=timezone.now(), how=how, declined_by=declined_by or []
    )
    audit.record(member.number, "union.delegate_started", union, unit=unit.slug, how=how)
    return row


def _end_delegate(row):
    row.ends_at = timezone.now()
    row.save(update_fields=["ends_at"])


def _hand_over_delegate(union, unit, how, exclude, declined_by=None):
    """End the current delegate's turn and start the next one. Caller holds the transaction."""
    current = UnionDelegate.objects.filter(union=union, unit=unit, ends_at__isnull=True).first()
    skip = set(exclude) | set(declined_by or [])
    chosen = _pick_delegate(union, unit, skip)
    if chosen is None:
        return None
    if current is not None:
        _end_delegate(current)
    row = _start_delegate(union, unit, chosen, how, declined_by)
    notify(
        chosen,
        _("You are now the delegate of %(unit)s in the union %(union)s.") % {"unit": unit.name, "union": union.name},
        f"/bodies/unions/{union.slug}/",
    )
    return row


def _first_delegate(union, unit):
    """The first delegate of a unit is its responsible at the time of joining (a one-person unit: its member)."""
    if UnionDelegate.objects.filter(union=union, unit=unit, ends_at__isnull=True).exists():
        return
    chosen = _unit_responsible_member(unit)
    if chosen is not None:
        _start_delegate(union, unit, chosen, "first")


def _unit_left_union(union, unit):
    UnionDelegate.objects.filter(union=union, unit=unit, ends_at__isnull=True).update(ends_at=timezone.now())


UNIT_JOINED_HOOKS.append(_first_delegate)
UNIT_LEFT_HOOKS.append(_unit_left_union)


def hand_over_delegates_of(unit, member):
    """A worker left the unit or Unicorn: every delegate role the person held passes on at once."""
    rows = UnionDelegate.objects.filter(unit=unit, member=member, ends_at__isnull=True).select_related("union")
    for row in list(rows):
        with transaction.atomic():
            if _hand_over_delegate(row.union, unit, "handover", exclude={member.pk}) is None:
                _end_delegate(row)  # nobody is left in the unit to speak for it


def _worker_left(unit, member):
    hand_over_delegates_of(unit, member)


def _leave_check(member):
    for row in UnionDelegate.objects.filter(member=member, ends_at__isnull=True).select_related("unit"):
        hand_over_delegates_of(row.unit, member)
    return []


def rotate_delegates(now=None) -> int:
    """After the union's rotation time, a unit's next delegate is chosen among its council members."""
    now = now or timezone.now()
    count = 0
    rows = UnionDelegate.objects.filter(ends_at__isnull=True).select_related("union", "unit", "member")
    for row in rows:
        union, unit = row.union, row.unit
        if union.status == "dissolved" or not unit_services.is_worker(row.member, unit):
            if union.status != "dissolved":
                hand_over_delegates_of(unit, row.member)
            continue
        rules = current_rules(union)
        months = rules.rotation_months if rules else get_param("governance.unions.delegate_rotation_months")
        if member_services._add_months(row.starts_at, months) > now:
            continue
        with transaction.atomic():
            fresh = UnionDelegate.objects.select_for_update().get(pk=row.pk)
            if fresh.ends_at is not None:
                continue
            if _hand_over_delegate(union, unit, "rotation", exclude={row.member_id}) is not None:
                count += 1
    return count


def decline_delegate_turn(member, union, unit):
    with transaction.atomic():
        row = UnionDelegate.objects.select_for_update().filter(union=union, unit=unit, ends_at__isnull=True).first()
        if row is None or row.member_id != member.pk:
            raise BodyError(_("You are not the delegate of this unit."))
        declined = list(row.declined_by) + [member.pk]
        new = _hand_over_delegate(union, unit, "rotation", exclude={member.pk}, declined_by=declined)
        if new is None:
            raise BodyError(_("Nobody else in the unit can take the role."))
        return new


# --- Union decisions (P13.T03) ---

# What a union decision may do (HF-15, HF-20). A union decision never changes a unit, an offer, an hours entry,
# a council's rules or a parameter. Anything not on this list is refused.
ALLOWED_ACTIONS = ("publish_page", "publish_template", "nominate_expert", "create_task_list", "change_union_rules")
KIND_ACTIONS = {
    "standard": "publish_page",
    "recipe_template": "publish_template",
    "nominate_expert": "nominate_expert",
    "training": "create_task_list",
    "rules_change": "change_union_rules",
    "other": None,
}
ACTIONS: dict = {}  # action name -> function(decision) -> dict


def register_action(name, fn):
    if name not in ALLOWED_ACTIONS:
        raise BodyError(_("A union decision may not do this: %(action)s.") % {"action": name})
    ACTIONS[name] = fn


def _action_for(kind, payload):
    name = (payload or {}).get("action") or KIND_ACTIONS.get(kind)
    if name is not None and name not in ALLOWED_ACTIONS:
        raise BodyError(
            _("A union only advises and decides its own work. It cannot do this: %(action)s.") % {"action": name}
        )
    return name


def open_decision(member, union, title, text="", kind="other", payload=None):
    """A delegate opens a decision of the union."""
    if kind not in KIND_ACTIONS:
        raise BodyError(_("This kind of decision does not exist."))
    if union.status != "active":
        raise BodyError(_("The union can decide once enough units have joined."))
    if not member_services.is_verified(member) or delegate_for(member, union) is None:
        raise BodyError(_("Only the delegates of the union can open a decision."))
    if not (title or "").strip():
        raise BodyError(_("Please give the decision a title."))
    payload = dict(payload or {})
    _action_for(kind, payload)  # refuses anything outside the allow-list before a vote is wasted
    if kind == "rules_change":
        problems = rule_problems(payload)
        if problems:
            raise BodyError(problems[0])
    rules = current_rules(union)
    now = timezone.now()
    with transaction.atomic():
        decision = UnionDecision.objects.create(
            union=union,
            title=title.strip()[:120],
            text=text,
            kind=kind,
            payload=payload,
            opened_by=member,
            opens_at=now,
            closes_at=now + timedelta(days=rules.vote_days),
        )
        audit.record(member.number, "union.decision_opened", decision, kind=kind)
        if len(current_delegates(union)) <= 1:  # nobody else to ask
            _finish(decision, True, {"one_delegate": True})
        return decision


def vote(decision, member, choice):
    if choice not in ("yes", "no", "abstain"):
        raise BodyError(_("Please answer yes, no or abstain."))
    with transaction.atomic():
        decision = UnionDecision.objects.select_for_update().get(pk=decision.pk)
        if decision.status != "open" or timezone.now() >= decision.closes_at:
            raise BodyError(_("This decision is closed."))
        row = delegate_for(member, decision.union) if member_services.is_verified(member) else None
        if row is None:
            raise BodyError(_("Only the delegates of the union can vote."))
        if UnionVote.objects.filter(decision=decision, unit=row.unit).exists():
            raise BodyError(_("Your unit has already voted."))
        UnionVote.objects.create(decision=decision, unit=row.unit, member=member, vote=choice)
        audit.record(member.number, "union.decision_voted", decision)
        voted = set(decision.votes.values_list("unit_id", flat=True))
        if {d.unit_id for d in current_delegates(decision.union)} <= voted:
            tally(decision)
        return decision


def tally(decision):
    """Count the votes of the units that still have a delegate and close the decision. Safe to call twice."""
    with transaction.atomic():
        decision = UnionDecision.objects.select_for_update().get(pk=decision.pk)
        if decision.status != "open":
            return decision
        unit_ids = {d.unit_id for d in current_delegates(decision.union)}
        votes = [v.vote for v in decision.votes.all() if v.unit_id in unit_ids]
        rules = current_rules(decision.union)
        counted = count(votes, rules.decision_rule, rules.quorum, len(unit_ids))
        result = {
            "yes": counted.yes,
            "no": counted.no,
            "abstain": counted.abstain,
            "units": len(unit_ids),
            "rule": rules.decision_rule,
        }
        if not counted.quorum_met:
            result["reason"] = "quorum"
        return _finish(decision, counted.approved, result)


def _finish(decision, approved, result):
    decision.status = "approved" if approved else "rejected"
    decision.result = result
    decision.save(update_fields=["status", "result"])
    audit.record("system", "union.decision_closed", decision, status=decision.status)
    if approved:
        name = _action_for(decision.kind, decision.payload)  # checked again when it runs (HF-20)
        if name is not None:
            fn = ACTIONS.get(name)
            if fn is not None:
                decision.result = {**decision.result, "done": fn(decision) or {}}
                decision.save(update_fields=["result"])
    return decision


def close_due_decisions(now=None) -> int:
    count_closed = 0
    for d in UnionDecision.objects.filter(status="open", closes_at__lte=now or timezone.now()):
        tally(d)
        count_closed += 1
    return count_closed


RULE_FIELDS = ("decision_rule", "quorum", "vote_days", "rotation_months", "clauses_md")


def rule_problems(values) -> list[str]:
    from decimal import Decimal, InvalidOperation

    from apps.units import council_rules

    problems = []
    if values.get("decision_rule", "majority") not in ("consensus", "majority", "two_thirds"):
        problems.append(_("The decision rule must be consensus, majority or two thirds."))
    try:
        if not Decimal("0") <= Decimal(str(values.get("quorum", "0.5"))) <= Decimal("1"):
            problems.append(_("The quorum must be between 0 and 1."))
    except InvalidOperation:
        problems.append(_("The quorum must be a number."))
    for key, top in (("vote_days", 60), ("rotation_months", 36)):
        try:
            if not 1 <= int(values.get(key, 1)) <= top:
                problems.append(_("Please use a number from 1 to %(top)s.") % {"top": top})
        except (TypeError, ValueError):
            problems.append(_("Please use a whole number."))
    return problems + council_rules.validate_clauses(values.get("clauses_md", ""))


def _change_union_rules(decision):
    """A union changes only its own rules."""
    from decimal import Decimal

    old = current_rules(decision.union)
    merged = {f: getattr(old, f) for f in RULE_FIELDS}
    merged.update({k: v for k, v in decision.payload.items() if k in RULE_FIELDS})
    merged["quorum"] = Decimal(str(merged["quorum"]))
    rules = UnionRules.objects.create(
        union=decision.union, version=old.version + 1, adopted_at=timezone.now(), adopted_by=decision, **merged
    )
    audit.record("system", "union.rules_adopted", decision.union, version=rules.version)
    return {"version": rules.version}


register_action("change_union_rules", _change_union_rules)


# --- The ticket actions ---


def _ids(ticket):
    from apps.units.models import Unit

    p = ticket.action_payload
    return Union.objects.get(pk=p["union_id"]), Unit.objects.get(pk=p["unit_id"])


def _union_join(ticket):
    union, unit = _ids(ticket)
    add_unit(union, unit, ticket=ticket)
    union.refresh_from_db()
    return {"union": union.slug, "status": union.status}


def _union_leave(ticket):
    union, unit = _ids(ticket)
    remove_unit(union, unit)
    union.refresh_from_db()
    return {"union": union.slug, "status": union.status}


def register():
    from apps.tickets import actions

    need = actions._need("union_id", "unit_id")
    actions.register("union_join", _union_join, need)
    actions.register("union_leave", _union_leave, need)
    if _worker_left not in unit_services.WORKER_LEFT_HOOKS:
        unit_services.WORKER_LEFT_HOOKS.append(_worker_left)
    if _leave_check not in member_services.LEAVE_CHECKS:
        member_services.LEAVE_CHECKS.append(_leave_check)
