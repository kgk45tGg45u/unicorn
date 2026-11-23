"""Unions: forming, joining and leaving (docs/05 section 7). A union advises and never commands (HF-15, HF-20)."""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.notify import notify
from apps.members import services as member_services
from apps.rules.services import get_param
from apps.tickets import services as ticket_services
from apps.units import services as unit_services

from .models import Union, UnionMembership, UnionRules

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
