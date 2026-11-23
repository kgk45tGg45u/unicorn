"""Members' bills: benefit and guarantee claims (docs/07 section 9).

Benefits are paid by need, heaviest burden first, within a monthly budget that follows the simulation's rule. The
guarantee comes before them. Every payment is a payment request that people carry out and confirm (HF-12).
"""

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.money import cur
from apps.core.notify import notify
from apps.members import services as member_services
from apps.rules.services import get_param

from . import allocation, fx, payers, payments
from .models import (
    BenefitBill,
    BenefitBudget,
    BenefitClaim,
    BenefitPayout,
    FundEntry,
    GuaranteeClaim,
)
from .services import FundError

ONE = Decimal(1)


def _first(day):
    return day.replace(day=1)


# --- Filing a claim ---


def file_claim(member, bills, income_eur, documents=()):
    """`bills`: dicts with kind, amount_eur and optionally payee_name and payee_iban (else the member is paid)."""
    from apps.tickets import services as ticket_services
    from apps.tickets.briefs import _check

    if not member_services.is_verified(member):  # HF-13
        raise FundError(_("Only verified members can claim a benefit."))
    if BenefitClaim.objects.filter(member=member, status__in=("confirming", "approved", "active", "paused")).exists():
        raise FundError(_("You already have a claim. You can end it and file a new one."))
    if not bills:
        raise FundError(_("Please add at least one bill."))
    kinds = {k for k, _l in BenefitBill.KINDS}
    clean = []
    for b in bills:
        amount = cur(Decimal(str(b.get("amount_eur", "0")).replace(",", ".")))
        if amount <= 0 or b.get("kind") not in kinds:
            raise FundError(_("Each bill needs a kind and an amount above zero."))
        clean.append({**b, "amount_eur": amount})
    income = cur(Decimal(str(income_eur or "0").replace(",", ".")))
    if income < 0:
        raise FundError(_("Your income cannot be negative."))
    total = sum((b["amount_eur"] for b in clean), Decimal(0))
    with transaction.atomic():
        claim = BenefitClaim.objects.create(
            member=member,
            status="confirming",
            income_eur=income,
            burden_score=(total / max(income, ONE)).quantize(Decimal("0.0001")),
        )
        for b in clean:
            payee = None
            if (b.get("payee_iban") or "").strip():
                payee = payments.new_external_payee(member, b.get("payee_name", ""), b["payee_iban"])
            BenefitBill.objects.create(claim=claim, kind=b["kind"], amount_eur=b["amount_eur"], payee_external=payee)
        claim.documents.set(documents)
        # The brief shows the bills and the burden, never the name: only the seats see the documents.
        lines = [
            _("A member asks the fund to pay %(total)s euros a month of their basic bills.") % {"total": total},
            *[f"- {dict(BenefitBill.KINDS)[b['kind']]}: {b['amount_eur']}" for b in clean],
            _("Their own euro income is %(income)s a month, so the bills are %(burden)s times their income.")
            % {"income": income, "burden": claim.burden_score},
            _("You can open the documents on this ticket. Do you agree that the fund should help?"),
        ]
        check = _check(
            _("How many euros a month are asked for in total?"),
            str(total),
            [str(cur(total * 2)), str(cur(total / 2))],
            _("the first sentence"),
        )
        ticket = ticket_services.create_ticket(
            "benefit_claim",
            member,
            _("A claim for help with basic bills"),
            brief="\n".join(lines),
            check=check,
            action_payload={"claim_id": claim.pk, "document_ids": [d.pk for d in documents]},
        )
        claim.ticket = ticket
        claim.save(update_fields=["ticket"])
        audit.record(member.number, "benefit.filed", claim, total=str(total))
        return claim


def file_guarantee(member, month, shortfall_eur, explanation):
    from apps.tickets import services as ticket_services
    from apps.tickets.briefs import _check

    if not get_param("economy.benefits.guarantee"):
        raise FundError(_("The guarantee is switched off."))
    if not member_services.is_verified(member):  # HF-13
        raise FundError(_("Only verified members can claim the guarantee."))
    shortfall = cur(Decimal(str(shortfall_eur).replace(",", ".")))
    if shortfall <= 0 or not (explanation or "").strip():
        raise FundError(_("Please say how much was missing and why."))
    with transaction.atomic():
        claim = GuaranteeClaim.objects.create(
            member=member, month=_first(month), shortfall_eur=shortfall, explanation=explanation.strip()
        )
        brief = _(
            "A member says they are worse off on basic needs than without Unicorn in %(month)s, by %(amount)s euros. "
            "They explain: %(why)s Do you agree that the fund should top it up?"
        ) % {"month": f"{claim.month:%Y-%m}", "amount": shortfall, "why": claim.explanation[:600]}
        check = _check(
            _("How many euros were missing?"),
            str(shortfall),
            [str(cur(shortfall * 2)), str(cur(shortfall / 2))],
            _("the first sentence"),
        )
        ticket = ticket_services.create_ticket(
            "guarantee_claim",
            member,
            _("A claim for the basic-needs guarantee"),
            brief=brief,
            check=check,
            action_payload={"guarantee_id": claim.pk},
        )
        claim.ticket = ticket
        claim.save(update_fields=["ticket"])
        return claim


def end_claim(claim, member):
    if claim.member_id != member.pk:
        raise FundError(_("Only the member who filed the claim can end it."))
    claim.status = "ended"
    claim.save(update_fields=["status"])
    audit.record(member.number, "benefit.ended", claim)
    return claim


def _start_benefit(ticket):
    claim = BenefitClaim.objects.get(pk=ticket.action_payload["claim_id"])
    claim.status, claim.approved_monthly_eur = "active", claim.monthly_total
    claim.save(update_fields=["status", "approved_monthly_eur"])
    notify(
        claim.member,
        _("Your claim was approved. The fund pays it every month while the budget lasts."),
        "/fund/benefits/",
    )
    return {"claim": claim.pk}


def _benefit_rejected(ticket):
    claim = BenefitClaim.objects.filter(pk=(ticket.action_payload or {}).get("claim_id")).first()
    if claim is not None and claim.status == "confirming":
        claim.status = "rejected"
        claim.save(update_fields=["status"])
        notify(
            claim.member, _("Your claim was not approved. The reasons are on the ticket."), f"/tickets/{ticket.number}/"
        )
    return {"claim": claim.pk if claim else None}


def _start_guarantee(ticket):
    claim = GuaranteeClaim.objects.get(pk=ticket.action_payload["guarantee_id"])
    claim.status = "approved"
    claim.save(update_fields=["status"])
    notify(claim.member, _("Your guarantee claim was approved. It is paid first this month."), "/fund/benefits/")
    return {"guarantee": claim.pk}


def _guarantee_rejected(ticket):
    claim = GuaranteeClaim.objects.filter(pk=(ticket.action_payload or {}).get("guarantee_id")).first()
    if claim is not None and claim.status == "confirming":
        claim.status = "rejected"
        claim.save(update_fields=["status"])
    return {"guarantee": claim.pk if claim else None}


# --- The budget (docs/07 section 9; simulation trade.benefits.*) ---


def budget_for(month) -> BenefitBudget:
    """The month's budget, set once. It moves 1/adjust_months of the way toward the target each month."""
    from apps.macro import services as macro

    month = _first(month)
    row = BenefitBudget.objects.filter(month=month).first()
    if row is not None:
        return row
    now = timezone.now()
    received_rows = FundEntry.objects.filter(
        kind__in=("setaside", "donation"), created_at__gte=now - timedelta(days=365)
    ).values_list("currency", "amount")
    received = sum((fx.to_eur(a, c) for c, a in received_rows), Decimal(0))
    other, months = allocation.outgoings_last_12_months(month, exclude_reason=("bill",))
    target = max(Decimal(0), (received - other) / months)
    previous = BenefitBudget.objects.filter(month__lt=month).order_by("-month").first()
    prev = previous.budget_eur if previous else Decimal(0)
    note = ""
    reserve = allocation.reserve_months(month)
    if reserve is not None and reserve < Decimal(str(get_param("tradefund.reserve_min_months"))):
        budget = prev * (1 - Decimal(str(get_param("economy.benefits.cut_per_month_below_min_reserve"))))
        note = _("Cut: the euro reserve is below its minimum.")
    else:
        budget = prev + (target - prev) / get_param("economy.benefits.adjust_months")
        attractiveness = macro.attractiveness()
        # OWNER-CHECK: until the world is measured (P09), an unknown attractiveness counts as satisfied.
        satisfied = attractiveness is None or attractiveness >= Decimal(
            str(get_param("economy.benefits.min_attractiveness"))
        )
        if budget > prev and not satisfied:
            budget, note = prev, _("Not raised: an hour in Unicorn does not buy enough yet.")
    return BenefitBudget.objects.create(month=month, target_eur=cur(target), budget_eur=cur(budget), note=note)


# --- The monthly payments ---


def _pay_claim(month, kind, ref_id, member, bills, ticket=None):
    """Make the payment requests for one claim. Returns True when they were made."""
    total = sum((amount for _k, amount, _p in bills), Decimal(0))
    try:
        with transaction.atomic():
            for bill_kind, amount, payee in bills:
                common = dict(
                    amount=amount,
                    currency="EUR",
                    ticket=ticket,
                    description=_("%(kind)s for %(month)s") % {"kind": bill_kind, "month": f"{month:%Y-%m}"},
                    purpose="benefit",
                    ref=(kind, ref_id),
                    confirmer=member,
                )
                parts = payers.choose_payers(amount, "EUR")
                if not parts:
                    raise FundError(_("The fund cannot pay this month."))
                for holder, part in parts:
                    kwargs = dict(common, amount=part)
                    if payee is not None:
                        payments.request_payment(payer=holder, reason_kind="bill", payee_external=payee, **kwargs)
                    else:
                        payments.request_payment(payer=holder, reason_kind="gift", payee_member=member, **kwargs)
    except FundError as e:
        BenefitPayout.objects.update_or_create(
            month=month,
            kind=kind,
            ref_id=ref_id,
            defaults={"amount_eur": total, "status": "waiting", "note": str(e)[:200]},
        )
        return False
    BenefitPayout.objects.update_or_create(
        month=month, kind=kind, ref_id=ref_id, defaults={"amount_eur": total, "status": "requested", "note": ""}
    )
    return True


def run_monthly(month=None, now=None) -> dict:
    """Pay approved guarantee claims first, then active benefit claims by burden, while the budget lasts.

    Safe to run twice: a claim that was paid for the month is not paid again. Claims that did not fit wait for the
    next run, and the member is told why once."""
    now = now or timezone.now()
    month = _first(month or timezone.localdate())
    budget = budget_for(month)
    spent = sum((p.amount_eur for p in BenefitPayout.objects.filter(month=month, status="requested")), Decimal(0))
    left = budget.budget_eur - spent
    result = {"guarantee": 0, "benefits": 0, "waiting": 0}

    def tell(member, text, payout_key):
        # told once: the waiting row is created or updated, the notice goes out only when it is new
        notify(member, text, "/fund/benefits/")

    guarantees = GuaranteeClaim.objects.filter(status="approved", month__lte=month).order_by("id")
    for g in guarantees:
        if BenefitPayout.objects.filter(month=month, kind="guarantee", ref_id=g.pk, status="requested").exists():
            continue
        if g.shortfall_eur > left:
            already = BenefitPayout.objects.filter(
                month=month, kind="guarantee", ref_id=g.pk, status="waiting"
            ).exists()
            BenefitPayout.objects.update_or_create(
                month=month,
                kind="guarantee",
                ref_id=g.pk,
                defaults={
                    "amount_eur": g.shortfall_eur,
                    "status": "waiting",
                    "note": _("The budget for this month is used up."),
                },
            )
            if not already:
                tell(g.member, _("Your guarantee claim waits: the budget for this month is used up."), g.pk)
            result["waiting"] += 1
            continue
        if _pay_claim(month, "guarantee", g.pk, g.member, [("basic needs", g.shortfall_eur, None)], g.ticket):
            g.status = "paid"
            g.save(update_fields=["status"])
            left -= g.shortfall_eur
            result["guarantee"] += 1
        else:
            result["waiting"] += 1

    claims = sorted(
        BenefitClaim.objects.filter(status="active").prefetch_related("bills__payee_external"),
        key=lambda c: (-c.burden_score, c.pk),
    )
    for c in claims:
        if BenefitPayout.objects.filter(month=month, kind="benefit", ref_id=c.pk, status="requested").exists():
            continue
        amount = c.approved_monthly_eur
        if amount > left:
            already = BenefitPayout.objects.filter(month=month, kind="benefit", ref_id=c.pk, status="waiting").exists()
            BenefitPayout.objects.update_or_create(
                month=month,
                kind="benefit",
                ref_id=c.pk,
                defaults={
                    "amount_eur": amount,
                    "status": "waiting",
                    "note": _("The budget for this month is used up."),
                },
            )
            if not already:
                tell(
                    c.member,
                    _("Your claim waits this month: the benefit budget is used up. Heavier burdens come first."),
                    c.pk,
                )
            result["waiting"] += 1
            continue
        bills = [(dict(BenefitBill.KINDS)[b.kind], b.amount_eur, b.payee_external) for b in c.bills.all()]
        if _pay_claim(month, "benefit", c.pk, c.member, bills, c.ticket):
            left -= amount
            result["benefits"] += 1
        else:
            result["waiting"] += 1
    return result


def register():
    from apps.tickets import actions

    actions.register(
        "start_benefit",
        _start_benefit,
        lambda p: [] if p.get("claim_id") else [_("This ticket does not say what it is about.")],
    )
    actions.register(
        "start_guarantee",
        _start_guarantee,
        lambda p: [] if p.get("guarantee_id") else [_("This ticket does not say what it is about.")],
    )
    actions.register("benefit_rejected", _benefit_rejected)
    actions.register("guarantee_rejected", _guarantee_rejected)
