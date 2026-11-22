"""The monthly sample of one-person units (docs/06 section 3, owner 2026-11-22)."""

import math
import random
from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

from apps.core import audit
from apps.core.hashing import sha256_hex
from apps.core.models import AuditEvent
from apps.rules.services import get_param

from . import briefs, draw

DONE_VERB = "tickets.one_person_checks_done"


def one_person_units():
    """Open units with exactly one active worker, as (unit, member) pairs."""
    from apps.units import services as unit_services
    from apps.units.models import Unit

    pairs = []
    for unit in Unit.objects.filter(status__in=["trial", "open"]).exclude(kind="coordination").order_by("pk"):
        workers = list(unit_services.workers(unit))
        if len(workers) == 1:
            pairs.append((unit, workers[0].member))
    return pairs


def _already_done(marker) -> bool:
    recent = AuditEvent.objects.filter(verb=DONE_VERB, created_at__gte=timezone.now() - timedelta(days=40))
    return any(e.data.get("month") == marker for e in recent)


def one_person_checks(today=None) -> int:
    """Draw `sample_share_per_month` of the one-person units and open a check ticket for each. Once a month."""
    from apps.units.models import HoursEntry

    today = today or timezone.localdate()
    month = today.replace(day=1)
    marker = f"{month:%Y-%m}"
    if _already_done(marker):
        return 0
    last_month = (month - timedelta(days=1)).replace(day=1)
    pairs = one_person_units()
    share = get_param("governance.one_person_units.sample_share_per_month")
    k = min(len(pairs), math.ceil(len(pairs) * float(share))) if pairs else 0
    fp = draw._fingerprint()
    seed = sha256_hex(f"one_person:{marker}:{fp.hash if fp else draw.NO_FINGERPRINT}")
    for unit, member in random.Random(int(seed, 16)).sample(pairs, k):
        minutes = (
            HoursEntry.objects.filter(member=member, unit=unit, date__gte=last_month, date__lt=month).aggregate(
                t=Sum("minutes")
            )["t"]
            or 0
        )
        briefs.one_person_check(unit, member, last_month, minutes)
    audit.record("system", DONE_VERB, month=marker, checked=k, of=len(pairs))
    return k
