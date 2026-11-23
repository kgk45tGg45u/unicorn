"""Transfers: the equal pension and other transfers decided by tickets (docs/03 section 6).

Transfers are paid by Fund 2 and covered by the flat tax (HF-1, HF-9). The pension is the same for everyone.
"""

import statistics
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.money import uniq
from apps.ledger import services as ledger
from apps.ledger.models import Entry, Transaction
from apps.members.models import Member
from apps.rules.services import get_param

from .models import ActiveMonth, PensionRecognition, TransferPlan

ZERO = Decimal("0.0000")
EVIDENCE_DAYS = 30


def _first(day):
    return day.replace(day=1)


def _next_first(day):
    return (_first(day) + timedelta(days=32)).replace(day=1)


# --- Active months ---


def record_active_months(period) -> int:
    """`hours` for every member with at least `active_month_min_hours` approved hours in the month. Safe to rerun."""
    from apps.units.models import HoursEntry

    first = date(period.year, period.month, 1)
    minimum = Decimal(str(get_param("economy.pension.active_month_min_hours"))) * 60
    rows = (
        HoursEntry.objects.filter(
            date__gte=first, date__lt=_next_first(first), status__in=("approved", "paid", "pending_sale")
        )
        .values("member")
        .annotate(t=Sum("minutes"))
    )
    made = 0
    for row in rows:
        if Decimal(row["t"]) >= minimum:
            _row, created = ActiveMonth.objects.get_or_create(member_id=row["member"], month=first, kind="hours")
            made += int(created)
    return made


def active_months(member) -> int:
    return ActiveMonth.objects.filter(member=member).values("month").distinct().count()


# --- Who gets a pension ---


def pension_eligible(member) -> bool:
    # OWNER-CHECK: former members are not eligible here; should a former member who earned the right keep it?
    if member.status != Member.MEMBER or not get_param("economy.pension.enabled"):
        return False
    if active_months(member) < get_param("economy.pension.qualifying_active_months"):
        return False
    from apps.members import services as member_services

    return (
        member_services.has_reached_pension_age(member)
        or PensionRecognition.objects.filter(member=member, kind="unable_to_work").exists()
    )


def _net_income(member, first) -> Decimal:
    account = ledger.member_account(member)
    rows = Entry.objects.filter(
        account=account,
        transaction__kind__in=("hours_pay", "tax"),
        transaction__created_at__gte=timezone.make_aware(timezone.datetime(first.year, first.month, 1)),
        transaction__created_at__lt=timezone.make_aware(
            timezone.datetime(_next_first(first).year, _next_first(first).month, 1)
        ),
    )
    return rows.aggregate(t=Sum("amount"))["t"] or ZERO


def pension_amount(today=None) -> Decimal:
    """The share of the median monthly net UNIQ income of members with an `hours` month in the last 12 months."""
    today = today or timezone.localdate()
    start = _first(today) - timedelta(days=366)
    incomes = [
        _net_income(am.member, am.month)
        for am in ActiveMonth.objects.filter(kind="hours", month__gte=start, month__lt=_first(today)).select_related(
            "member"
        )
    ]
    incomes = [i for i in incomes if i > 0]
    if not incomes:
        return ZERO
    median = Decimal(str(statistics.median(incomes)))
    return uniq(median * Decimal(str(get_param("economy.pension.share_of_median_net"))))


def due_next_month(period) -> Decimal:
    """T in the tax balance: the pensions and other transfers due next month."""
    first = date(period.year, period.month, 1)
    nxt = _next_first(first)
    amount = pension_amount(first)
    pensions = amount * sum(1 for m in Member.objects.filter(status=Member.MEMBER) if pension_eligible(m))
    plans = _plans_due(nxt).aggregate(t=Sum("monthly_amount"))["t"] or ZERO
    return uniq(pensions + plans)


def _plans_due(month):
    return TransferPlan.objects.filter(from_month__lte=month).filter(Q(to_month__isnull=True) | Q(to_month__gte=month))


# --- Paying ---


def _already(ref_type, ref_id) -> bool:
    return Transaction.objects.filter(kind="transfer", ref_type=ref_type, ref_id=ref_id).exists()


def pay_transfers(today=None) -> dict:
    """Post this month's pensions and other transfers: Fund 2 to the member. Safe to run twice."""
    today = today or timezone.localdate()
    first = _first(today)
    month = f"{first:%Y-%m}"
    paid = {"pensions": 0, "plans": 0}
    amount = pension_amount(first)
    if amount > 0:
        for member in Member.objects.filter(status=Member.MEMBER, deleted=False):
            ref_id = f"{member.pk}:{month}"
            if _already("pension", ref_id) or not pension_eligible(member):
                continue
            with transaction.atomic():
                ledger.post(
                    "transfer",
                    f"Equal pension for {month}",
                    [ledger.Leg(ledger.fund2(), -amount), ledger.Leg(ledger.member_account(member), amount)],
                    ref=("pension", ref_id),
                )
            paid["pensions"] += 1
    for plan in _plans_due(first).select_related("member"):
        ref_id = f"{plan.pk}:{month}"
        if _already("transferplan", ref_id):
            continue
        with transaction.atomic():
            ledger.post(
                "transfer",
                f"{plan.reason} ({month})",
                [
                    ledger.Leg(ledger.fund2(), -plan.monthly_amount),
                    ledger.Leg(ledger.member_account(plan.member), plan.monthly_amount),
                ],
                ref=("transferplan", ref_id),
            )
        paid["plans"] += 1
    return paid


# --- Tickets: recognised months, and "unable to work" ---


def _record_month(ticket):
    p = ticket.action_payload
    member = Member.objects.get(number=p["member"])
    first = date.fromisoformat(p["month"] + "-01")
    ActiveMonth.objects.get_or_create(member=member, month=first, kind=p.get("kind", "care"))
    return {"member": member.number, "month": p["month"]}


def _recognise_unable(ticket):
    member = Member.objects.get(number=ticket.action_payload["member"])
    evidence_id = ticket.action_payload.get("document_id")
    rec = PensionRecognition.objects.create(
        member=member,
        kind="unable_to_work",
        ticket=ticket,
        evidence_id=evidence_id,
        delete_evidence_at=timezone.now() + timedelta(days=EVIDENCE_DAYS),
    )
    audit.record("system", "pension.recognised", rec)
    return {"recognition": rec.pk}


def shred_evidence(now=None) -> int:
    """Thirty days after the decision the evidence is gone: the stored bytes are deleted."""
    from pathlib import Path

    from django.conf import settings

    now = now or timezone.now()
    done = 0
    for rec in PensionRecognition.objects.filter(
        delete_evidence_at__lte=now, evidence__isnull=False, evidence_shredded_at__isnull=True
    ).select_related("evidence"):
        path = Path(settings.PRIVATE_MEDIA_ROOT) / rec.evidence.path
        if path.exists():
            path.unlink()
        rec.evidence_shredded_at = now
        rec.save(update_fields=["evidence_shredded_at"])
        done += 1
    return done


def register():
    from apps.tickets import actions

    need = lambda *k: lambda p: [] if all(p.get(x) for x in k) else [_("This ticket does not say what it is about.")]  # noqa: E731
    actions.register("record_active_month", _record_month, need("member", "month"))
    actions.register("recognise_unable_to_work", _recognise_unable, need("member"))
