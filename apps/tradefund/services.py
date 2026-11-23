"""Holders (docs/07 section 2). The app never moves money (HF-12): it records what people confirm."""

from django.db import transaction
from django.utils.translation import gettext as _

from apps.core import audit
from apps.members import services as member_services
from apps.members.models import ContractTemplate

from .models import Holder


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
        audit.record(member.number, "holder.joined", holder, currency=currency)
        return holder
