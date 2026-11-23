"""Local councils (docs/05 section 7, P13.T06): the members of an area decide local matters through tickets.

Who belongs is computed from the member's country and postcode, so moving house changes it at once.
"""

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.notify import notify
from apps.core.rotation import next_in_rotation
from apps.members import services as member_services
from apps.members.models import Member
from apps.rules.services import get_param
from apps.tickets import briefs
from apps.tickets import services as ticket_services
from apps.tickets.models import Ticket

from . import services
from .models import LocalCouncil, LocalResponsibility, LocalVolunteer

# --- Who belongs ---


def members_in_area(country, prefix):
    """Every verified member whose country matches and whose postcode starts with the prefix."""
    return Member.objects.filter(
        status=Member.MEMBER, deleted=False, country=country.upper(), postcode__startswith=prefix
    )


def belongs(member, council) -> bool:
    return (
        member_services.is_verified(member)
        and not member.deleted
        and member.country == council.country
        and member.postcode.startswith(council.postcode_prefix)
    )


def councils_of(member):
    """The councils a member belongs to now: a district, its town and so on."""
    if not member_services.is_verified(member) or not member.postcode:
        return []
    return [
        c
        for c in LocalCouncil.objects.filter(status="active", country=member.country)
        if member.postcode.startswith(c.postcode_prefix)
    ]


# --- Opening a council ---


def _area_check(council_name, prefix):
    return briefs._check(
        _("Which area is this about?"),
        council_name,
        [_("The whole country"), _("A single unit")],
        _("the first sentence"),
    )


def propose_council(member, name, prefix, level="town", country=None):
    """A member of the area asks to open a council. It needs enough members, and random members of the area decide."""
    prefix = (prefix or "").strip().replace(" ", "")
    country = (country or member.country).upper()
    name = (name or "").strip()
    if not name or not prefix:
        raise services.BodyError(_("Please give the council a name and the start of the postcode."))
    if level not in dict(LocalCouncil.LEVELS):
        raise services.BodyError(_("Please choose district, town, region or country."))
    if not member_services.is_verified(member) or member.country != country or not member.postcode.startswith(prefix):
        raise services.BodyError(_("Only members who live in the area can ask for its council."))
    if LocalCouncil.objects.filter(country=country, postcode_prefix=prefix).exists():
        raise services.BodyError(_("There is already a council for this area."))
    needed = get_param("governance.local.min_members")
    have = members_in_area(country, prefix).count()
    if have < needed:
        raise services.BodyError(
            _("Not enough members live here yet: %(have)s of the %(needed)s needed.") % {"have": have, "needed": needed}
        )
    text = _("%(member)s asks to open the local council %(name)s for the postcodes starting with %(prefix)s.") % {
        "member": member.number,
        "name": name,
        "prefix": prefix,
    }
    return ticket_services.create_ticket(
        "local_council_open",
        member,
        _("Open the local council %(name)s") % {"name": name},
        text,
        scope="local",
        scope_area=prefix,
        scope_country=country,
        brief=text + " " + _("Do you agree that the council should open?"),
        check=_area_check(name, prefix),
        action_payload={"name": name, "prefix": prefix, "level": level, "country": country},
    )


def _council_problems(payload):
    keys = ("name", "prefix", "level", "country")
    return [] if all(payload.get(k) for k in keys) else [_("This ticket does not say which council it opens.")]


def _open_council(ticket):
    p = ticket.action_payload
    have = members_in_area(p["country"], p["prefix"]).count()
    if have < get_param("governance.local.min_members"):
        raise services.BodyError(_("Fewer members live in this area than the council needs."))
    council = LocalCouncil.objects.create(
        name=p["name"], country=p["country"], postcode_prefix=p["prefix"], level=p["level"], ticket=ticket
    )
    audit.record("system", "local.council_opened", council, ticket=ticket.number)
    return {"council": council.pk}


# --- The responsible ---


def current_responsible(council):
    return LocalResponsibility.objects.filter(council=council, ends_at__isnull=True).select_related("member").first()


def days_held(council, member, now=None) -> int:
    now = now or timezone.now()
    rows = LocalResponsibility.objects.filter(council=council, member=member)
    return sum(((r.ends_at or now) - r.starts_at).days for r in rows)


def active_volunteers(council):
    """Volunteers who still belong to the area (moving away ends the offer)."""
    return [
        v
        for v in council.volunteers.filter(withdrawn_at__isnull=True).select_related("member")
        if belongs(v.member, council)
    ]


def volunteer(member, council):
    """A member of the area offers to be the responsible in turn. The first volunteer starts at once."""
    if council.status != "active" or not belongs(member, council):
        raise services.BodyError(_("Only members who live in the area can volunteer."))
    with transaction.atomic():
        row, created = LocalVolunteer.objects.get_or_create(
            council=council, member=member, withdrawn_at=None, defaults={"joined_at": timezone.now()}
        )
        if created:
            audit.record(member.number, "local.volunteered", council)
            if current_responsible(council) is None:
                _start(council, member, "volunteer")
        return row


def withdraw(member, council):
    with transaction.atomic():
        LocalVolunteer.objects.filter(council=council, member=member, withdrawn_at__isnull=True).update(
            withdrawn_at=timezone.now()
        )
        current = current_responsible(council)
        if current is not None and current.member_id == member.pk:
            _hand_over(council, "handover", exclude={member.pk})


def _start(council, member, how, declined_by=None):
    row = LocalResponsibility.objects.create(
        council=council, member=member, starts_at=timezone.now(), how=how, declined_by=declined_by or []
    )
    audit.record(member.number, "local.responsible_started", council, how=how)
    notify(
        member,
        _("You are now the responsible of the local council %(name)s.") % {"name": council.name},
        f"/bodies/local/{council.pk}/",
    )
    return row


def _hand_over(council, how, exclude, declined_by=None):
    """End the current turn and start the next volunteer's. Without another volunteer the role stays empty."""
    current = current_responsible(council)
    skip = set(exclude) | set(declined_by or [])
    candidates = [(v.member, v.joined_at) for v in active_volunteers(council)]
    chosen = next_in_rotation(candidates, lambda m: days_held(council, m), skip)
    if current is not None:
        current.ends_at = timezone.now()
        current.save(update_fields=["ends_at"])
    if chosen is None:
        return None
    return _start(council, chosen, how, declined_by)


def decline_turn(member, council):
    with transaction.atomic():
        current = current_responsible(council)
        if current is None or current.member_id != member.pk:
            raise services.BodyError(_("You are not the responsible of this council."))
        declined = list(current.declined_by) + [member.pk]
        return _hand_over(council, "rotation", exclude={member.pk}, declined_by=declined)


def rotate_local(now=None) -> int:
    """Pass the role on after `governance.local.rotation_months`; repair a role whose holder moved away."""
    from apps.members.services import _add_months

    now = now or timezone.now()
    months = get_param("governance.local.rotation_months")
    changed = 0
    for council in LocalCouncil.objects.filter(status="active"):
        with transaction.atomic():
            current = current_responsible(council)
            if current is None:
                if active_volunteers(council):
                    _hand_over(council, "handover", exclude=set())
                    changed += 1
                continue
            gone = not belongs(current.member, council)
            if gone:
                _hand_over(council, "handover", exclude={current.member_id})
                changed += 1
            elif _add_months(current.starts_at, months) <= now:
                others = [v for v in active_volunteers(council) if v.member_id != current.member_id]
                if others:
                    _hand_over(council, "rotation", exclude={current.member_id})
                    changed += 1
    return changed


# --- Local matters ---

# local action name -> (function(ticket, council) -> dict, function(payload) -> list of problems)
LOCAL_ACTIONS: dict = {}


def propose_decision(member, council, title, text, local_action="record", payload=None):
    """A member of the area proposes a local matter. Random members of the area confirm it."""
    if council.status != "active" or not belongs(member, council):
        raise services.BodyError(_("Only members who live in the area can propose a local decision."))
    if local_action not in LOCAL_ACTIONS:
        raise services.BodyError(_("This kind of local action does not exist."))
    brief = (text or title) + " " + _("Do you agree that this should go ahead?")
    return ticket_services.create_ticket(
        "local_decision",
        member,
        title,
        text,
        scope="local",
        scope_area=council.postcode_prefix,
        scope_country=council.country,
        brief=brief,
        check=_area_check(council.name, council.postcode_prefix),
        action_payload={"council": council.pk, "local_action": local_action, **(payload or {})},
    )


def _decision_problems(payload):
    from .models import LocalCouncil as Council

    if not Council.objects.filter(pk=payload.get("council")).exists():
        return [_("This ticket does not say which council it is for.")]
    entry = LOCAL_ACTIONS.get(payload.get("local_action"))
    if entry is None:
        return [_("This kind of local action does not exist.")]
    return entry[1](payload)


def _local_decision(ticket):
    council = LocalCouncil.objects.get(pk=ticket.action_payload["council"])
    result = LOCAL_ACTIONS[ticket.action_payload["local_action"]][0](ticket, council)
    audit.record("system", "local.decision_done", council, ticket=ticket.number)
    return result


def _record(ticket, council):
    return {"recorded": True}


def _open_point_problems(payload):
    p = payload.get("point") or {}
    ok = all((p.get(k) or "").strip() for k in ("name", "address", "postcode"))
    return [] if ok else [_("A pickup point needs a name, a public address and a postcode.")]


def _open_pickup_point(ticket, council):
    from apps.logistics import services as logistics

    p = ticket.action_payload["point"]
    if not p["postcode"].strip().startswith(council.postcode_prefix):
        raise services.BodyError(_("The pickup point must lie inside the council's area."))
    manager = Member.objects.filter(number=p.get("manager", "")).first()
    point = logistics.create_point(
        ticket.author, p["name"], p["address"], p["postcode"], country=council.country, notes=p.get("notes", ""),
        manager=manager,
    )  # fmt: skip
    point.managed_by_local_council = council
    point.save(update_fields=["managed_by_local_council"])
    return {"pickup_point": point.pk}


def _close_point_problems(payload):
    return [] if payload.get("point_id") else [_("Please say which pickup point closes.")]


def _close_pickup_point(ticket, council):
    from apps.logistics.models import PickupPoint

    point = PickupPoint.objects.get(pk=ticket.action_payload["point_id"], managed_by_local_council=council)
    point.active = False
    point.save(update_fields=["active"])
    return {"pickup_point": point.pk, "closed": True}


LOCAL_ACTIONS["record"] = (_record, lambda payload: [])
LOCAL_ACTIONS["open_pickup_point"] = (_open_pickup_point, _open_point_problems)
LOCAL_ACTIONS["close_pickup_point"] = (_close_pickup_point, _close_point_problems)


# --- What the council page shows ---


def area_needs(council, limit=10):
    """Search misses and wanted offers in the area (docs/06 section 7). Only a suggestion (HF-15)."""
    from apps.market.models import DemandSignal, SearchMiss

    prefix = council.postcode_prefix
    two = prefix[:2]
    misses = (
        SearchMiss.objects.filter(area__startswith=two)
        if len(prefix) >= 2
        else SearchMiss.objects.filter(area__startswith=prefix)
    )
    wanted = DemandSignal.objects.filter(
        flag="wanted", offer__unit__country=council.country, offer__unit__postcode__startswith=prefix
    ).select_related("offer__item", "offer__unit")
    return {"misses": list(misses[:limit]), "wanted": list(wanted[:limit])}


def area_pickup_points(council):
    return council.pickup_points.filter(active=True)


def area_helpers(council):
    """Members of the area who help others use the app: they hold at least one open consent (P13.T10)."""
    from apps.members import assist_services

    helpers = {}
    for member in members_in_area(council.country, council.postcode_prefix):
        if assist_services.open_consents_of(member):
            helpers[member.pk] = member
    return list(helpers.values())


def area_task_lists(council):
    return Ticket.objects.filter(
        type="task_list", scope="local", scope_area=council.postcode_prefix, scope_country=council.country
    )


def area_tickets(council):
    return Ticket.objects.filter(
        scope="local", scope_area=council.postcode_prefix, scope_country=council.country
    ).exclude(type="task_list")


def register():
    from apps.tickets import actions

    actions.register("open_local_council", _open_council, _council_problems)
    actions.register("local_decision", _local_decision, _decision_problems)
