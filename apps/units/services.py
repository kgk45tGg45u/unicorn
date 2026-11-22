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
    return get_param("governance.council.admission")


def _add_worker(unit, member):
    """Add an active worker. Caller holds the transaction."""
    membership = UnitMembership.objects.create(unit=unit, member=member, joined_at=timezone.now())
    audit.record(member.number, "unit.worker_joined", unit)
    if workers(unit).count() == 2:
        for hook in SECOND_WORKER_HOOKS:
            hook(unit)
    return membership


def add_first_worker(unit, member):
    with transaction.atomic():
        return _add_worker(unit, member)


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
