"""Retirement suggestions and payouts (docs/03 section 5, HF-8).

Nothing moves without the member's own click: the app only suggests (HF-8: UNIQ are never taken away or moved by
the system). Payouts after pension age are the member's own plan, in equal monthly parts.
"""

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.money import uniq
from apps.core.notify import notify
from apps.ledger import services as ledger
from apps.ledger.models import Account, Entry, Transaction
from apps.members import services as member_services
from apps.members.models import Member
from apps.rules.services import get_param

from .models import RetirementPlan

ZERO = Decimal("0.0000")


def savings_target(member, period, months=6) -> Decimal:
    """`economy.savings_target_months` of the member's own average monthly spending."""
    from .lights import _previous

    periods = _previous(period, months)
    spent = -(
        Entry.objects.filter(
            account__member=member,
            account__kind=Account.MEMBER,
            transaction__period__in=periods,
            transaction__kind__in=("purchase", "rent"),
        ).aggregate(t=Sum("amount"))["t"]
        or ZERO
    )
    return uniq(Decimal(str(get_param("economy.savings_target_months"))) * spent / len(periods))


def suggest(period, lights) -> int:
    """At a close, while the unspent-UNIQ light is amber or red: tell members above their target. Nothing moves."""
    if not get_param("economy.retirement.suggest_on_alarm"):
        return 0
    if (lights.get("unspent") or {}).get("color") not in ("amber", "red"):
        return 0
    share = Decimal(str(get_param("economy.retirement.suggest_share")))
    sent = 0
    for member in Member.objects.filter(status=Member.MEMBER, deleted=False):
        if audit_done(member, period):
            continue
        account = ledger.member_account(member)
        excess = ledger.balance(account) - savings_target(member, period)
        amount = uniq(excess * share)
        if amount <= 0:
            continue
        notify(
            member,
            _(
                "Unspent UNIQ are piling up. You could move %(amount)s UNIQ into your retirement account; it stays "
                "yours. Nothing moves unless you choose it."
            )
            % {"amount": amount},
            f"/me/retirement/?amount={amount}",
        )
        audit.record("system", "retirement.suggested", period, member=member.number)
        sent += 1
    return sent


def audit_done(member, period) -> bool:
    from apps.core.models import AuditEvent

    return AuditEvent.objects.filter(
        verb="retirement.suggested", object_type="Period", object_id=str(period.pk), data__member=member.number
    ).exists()


# --- Payouts after pension age ---


def start_plan(member) -> RetirementPlan:
    if not member_services.has_reached_pension_age(member):
        raise ledger.LedgerError(_("A payout plan can start after pension age."))
    plan, created = RetirementPlan.objects.get_or_create(member=member, defaults={"started_on": timezone.localdate()})
    if not created:  # started again: the months left count from today
        plan.active, plan.started_on = True, timezone.localdate()
        plan.save()
    audit.record(member.number, "retirement.plan_started", plan)
    return plan


def stop_plan(member):
    RetirementPlan.objects.filter(member=member).update(active=False)
    audit.record(member.number, "retirement.plan_stopped", member)


def _months_done(plan, today) -> int:
    return (today.year - plan.started_on.year) * 12 + today.month - plan.started_on.month


def pay_plans(today=None) -> int:
    """Each month: the retirement balance divided by the months left (out of `payout_months`). Safe to run twice."""
    today = today or timezone.localdate()
    month = f"{today:%Y-%m}"
    total_months = get_param("economy.retirement.payout_months")
    paid = 0
    for plan in RetirementPlan.objects.filter(active=True).select_related("member"):
        member = plan.member
        if not member_services.has_reached_pension_age(member):
            continue
        if Transaction.objects.filter(
            kind="retirement_out", ref_type="retirementplan", ref_id=f"{plan.pk}:{month}"
        ).exists():
            continue
        balance = ledger.balance(ledger.retirement_account(member))
        remaining = max(1, total_months - _months_done(plan, today))
        amount = uniq(balance / remaining)
        if amount <= 0:
            continue
        with transaction.atomic():
            ledger.post(
                "retirement_out",
                f"Retirement payout for {month}",
                [
                    ledger.Leg(ledger.retirement_account(member), -amount),
                    ledger.Leg(ledger.member_account(member), amount),
                ],
                ref=("retirementplan", f"{plan.pk}:{month}"),
                actor_ref=member.number,
            )
        paid += 1
    return paid
