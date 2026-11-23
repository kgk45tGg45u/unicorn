"""Holders (docs/07 section 2). The app never moves money (HF-12): it records what people confirm."""

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.money import cur
from apps.members import services as member_services
from apps.members.models import ContractTemplate

from . import fx
from .models import FundEntry, Holder


class FundError(ValueError):
    """Something the fund cannot do. The message is plain words for the member."""


def agreement():
    return ContractTemplate.objects.filter(kind="holder_agreement", is_current=True).first()


def is_holder(member) -> bool:
    return Holder.objects.filter(member=member, status__in=(Holder.ACTIVE, Holder.PAUSED, Holder.LEAVING)).exists()


def become_holder(member, currency, iban, bic="", bank_name="", separate_account=True, iban_shown_to_donors=False):
    """A verified member signs the holder agreement and gives the account number (stored encrypted)."""
    if not member_services.is_verified(member):  # HF-13
        raise FundError(_("Only verified members can hold euros for the group."))
    currency = (currency or "").upper()
    if len(currency) != 3:
        raise FundError(_("Please choose a currency."))
    iban = "".join((iban or "").split()).upper()
    if len(iban) < 8:
        raise FundError(_("Please enter the account number (IBAN) in which you will hold the euros."))
    template = agreement()
    if template is None:
        raise FundError(_("The holder agreement is not available yet."))
    with transaction.atomic():
        holder = Holder.objects.select_for_update().filter(member=member).first()
        if holder is not None and holder.status != Holder.LEFT:
            raise FundError(_("You are already a holder."))
        member_services.sign(member, template, "click", {"context": "holder"})
        member_services.set_private(member, iban=iban, bic=(bic or "").strip(), bank_name=(bank_name or "").strip())
        if holder is None:
            holder = Holder.objects.create(
                member=member,
                currency=currency,
                separate_account=bool(separate_account),
                iban_shown_to_donors=bool(iban_shown_to_donors),
            )
        else:  # a former holder starts again
            holder.status = Holder.ACTIVE
            holder.currency = currency
            holder.separate_account = bool(separate_account)
            holder.iban_shown_to_donors = bool(iban_shown_to_donors)
            holder.left_at = None
            holder.save()
        from . import trust

        if not holder.trust_events.exists():
            trust.start(holder)
        audit.record(member.number, "holder.joined", holder, currency=currency)
        return holder


# --- Leaving: a holder hands over their part first (docs/07 section 2) ---


def hand_over(holder):
    """Create payment requests that pass the holder's whole part to holders with room. Safe to run again: it only
    places what is not yet asked for. The status becomes `leaving`; when all are confirmed it becomes `left`."""
    from . import books, payers, payments, trust
    from .models import PaymentRequest

    with transaction.atomic():
        holder = Holder.objects.select_for_update().get(pk=holder.pk)
        if holder.status in (Holder.LEFT,):
            raise FundError(_("You are no longer a holder."))
        amount_held = books.holding(holder)
        pending = sum(
            (
                p.amount
                for p in PaymentRequest.objects.filter(payer=holder, purpose="handover", status__in=PaymentRequest.OPEN)
            ),
            Decimal(0),
        )
        if amount_held <= 0:
            holder.status, holder.left_at = Holder.LEFT, timezone.now()
            holder.save(update_fields=["status", "left_at"])
            return []
        reserve = books.reserve(holder)
        if reserve > 0:  # the loss reserve moves with the euros; the receivers mark it again
            books.post_fund(
                holder, "reserve_unmark", reserve, _("Handing over the whole holding."), "internal", ref=holder
            )
        left = amount_held - pending
        created = []
        receivers = sorted(
            (
                h
                for h in Holder.objects.filter(status=Holder.ACTIVE, currency=holder.currency).exclude(pk=holder.pk)
                if trust.room_eur(h) > 0
            ),
            key=lambda h: -trust.room_eur(h),
        )
        for target in receivers:
            if left <= 0:
                break
            room = cur(fx.from_eur(trust.room_eur(target), target.currency))
            part = min(left, room, payers.available(holder))
            if part <= 0:
                continue
            created.append(
                payments.request_payment(
                    payer=holder,
                    amount=part,
                    currency=holder.currency,
                    reason_kind="internal",
                    payee_holder=target,
                    description=_("Handing over a holding."),
                    purpose="handover",
                )
            )
            left -= part
        holder.status = Holder.LEAVING
        holder.save(update_fields=["status"])
        audit.record(holder.member.number, "holder.hand_over", holder, requests=len(created), unplaced=str(left))
        return created


def _handover_confirmed(payment):
    """When the last request of a handover is confirmed, the holder has left and the reserve is marked again."""
    from . import books, trust
    from .models import PaymentRequest

    if payment.purpose != "handover":
        return
    holder = Holder.objects.select_for_update().get(pk=payment.payer_id)
    if (
        books.holding(holder) > 0
        or PaymentRequest.objects.filter(payer=holder, purpose="handover", status__in=PaymentRequest.OPEN).exists()
    ):
        return
    holder.status, holder.left_at = Holder.LEFT, timezone.now()
    holder.save(update_fields=["status", "left_at"])
    audit.record(holder.member.number, "holder.left", holder)
    moved = FundEntry.objects.filter(
        holder=holder, kind="reserve_unmark", ref_type="holder", ref_id=str(holder.pk)
    ).aggregate(t=Sum("amount"))["t"]
    if moved:  # the loss reserve that went with the euros is marked again on the receivers
        trust.mark_reserve_amount(
            moved, holder.currency, ("holder", holder.pk), _("The loss reserve moves to other holders.")
        )
    trust.notify_holder(holder, _("You have passed on all you held. Thank you."), "/fund/me/")


def vanished(holder, why):
    """A holder disappeared with the group's euros: the score goes to zero and the loss reserve covers the amount."""
    from . import trust

    with transaction.atomic():
        holder = Holder.objects.select_for_update().get(pk=holder.pk)
        trust.record(holder, "left_without_handover", note=why)
        entry = trust.write_off(holder, why)
        holder.status, holder.left_at = Holder.LEFT, timezone.now()
        holder.save(update_fields=["status", "left_at"])
        audit.record("system", "holder.vanished", holder, written_off=str(entry.amount) if entry else "0")
        return entry


def _leave_check(member):
    """A holder who still holds euros must hand them over before leaving or deleting the account."""
    from . import books

    holder = Holder.objects.filter(member=member).exclude(status=Holder.LEFT).first()
    if holder is None:
        return []
    held = books.holding(holder)
    if held > 0:
        return [
            _("You still hold %(amount)s %(currency)s for the group. Please hand it over first (My holding).")
            % {"amount": held, "currency": holder.currency}
        ]
    holder.status, holder.left_at = Holder.LEFT, timezone.now()
    holder.save(update_fields=["status", "left_at"])
    return []


def register():
    from apps.members import services as member_services

    from . import payments

    if _leave_check not in member_services.LEAVE_CHECKS:
        member_services.LEAVE_CHECKS.append(_leave_check)
    if _handover_confirmed not in payments.CONFIRMED_HOOKS:
        payments.CONFIRMED_HOOKS.append(_handover_confirmed)
