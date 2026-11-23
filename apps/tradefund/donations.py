"""Donations in euros or US dollars (docs/07 section 8, HF-18).

A donation earns no UNIQ and is not tax-deductible. The donor pays into the account of a holder the app picks; the
holder confirms; the fund's books record it and a share is marked as loss reserve.
"""

from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.money import cur
from apps.members import crypto
from apps.members import services as member_services
from apps.rules.services import get_param

from . import books, fx, trust
from .models import Donation, Holder
from .services import FundError


def _amount(value) -> Decimal:
    try:
        amount = cur(Decimal(str(value).replace(",", ".")))
    except (InvalidOperation, ValueError, TypeError):
        raise FundError(_("Please enter the amount as a number, for example 25.00.")) from None
    if amount <= 0:
        raise FundError(_("The amount must be more than zero."))
    return amount


def pick_holder(amount, currency):
    """A holder in that currency who shows their account to donors and has room under their cap."""
    amount_eur = fx.to_eur(amount, currency)
    rooms = [
        (trust.room_eur(h), h)
        for h in Holder.objects.filter(status=Holder.ACTIVE, currency=currency, iban_shown_to_donors=True)
    ]
    rooms = [(r, h) for r, h in rooms if r >= amount_eur]
    if not rooms:
        return None
    return max(rooms, key=lambda rh: (rh[0], -rh[1].pk))[1]


def pledge(amount, currency, donor_member=None, donor_name="") -> Donation:
    """A donor says they will give. Returns the donation, with the holder who receives it."""
    currency = (currency or "").upper()
    if currency not in get_param("tradefund.donation_currencies"):
        raise FundError(
            _("The fund accepts donations in %(list)s.")
            % {"list": ", ".join(get_param("tradefund.donation_currencies"))}
        )
    amount = _amount(amount)
    holder = pick_holder(amount, currency)
    if holder is None:
        raise FundError(
            _("The fund cannot take a donation of this size in %(currency)s just now. Thank you for wanting to give.")
            % {"currency": currency}
        )
    with transaction.atomic():
        donation = Donation.objects.create(
            donor_member=donor_member,
            donor_name_enc=crypto.system_encrypt(donor_name.strip().encode()) if donor_name.strip() else b"",
            holder=holder,
            amount=amount,
            currency=currency,
        )
        audit.record(
            donor_member.number if donor_member else "outside", "donation.pledged", donation, amount=str(amount)
        )
        return donation


def holder_iban(donation) -> str:
    return member_services.get_private(donation.holder.member).get("iban", "")


def confirm_received(donation, member, amount=None) -> Donation:
    """The holder says the money arrived. The books record it; a share becomes loss reserve."""
    with transaction.atomic():
        donation = Donation.objects.select_for_update().get(pk=donation.pk)
        if member is None or member.pk != donation.holder.member_id:
            raise FundError(_("Only the holder who received the donation can confirm it."))
        if donation.status != "pledged":
            raise FundError(_("This donation was already dealt with."))
        amount = _amount(amount if amount not in (None, "") else donation.amount)
        _record(donation, amount)
        return donation


def _record(donation, amount):
    why = _("Donation %(ref)s. It earns no UNIQ and is not tax-deductible.") % {"ref": donation.reference}
    entry = books.post_fund(donation.holder, "donation", amount, why, "gift", ref=donation, currency=donation.currency)
    trust.mark_reserve(
        amount,
        donation.currency,
        ("donation", donation.pk),
        _("Loss reserve share of %(ref)s") % {"ref": donation.reference},
    )
    donation.amount, donation.status, donation.received_at = amount, "received", timezone.now()
    donation.save(update_fields=["amount", "status", "received_at"])
    audit.record("system", "donation.received", donation, entry=entry.seq)


def record_own_donation(holder, amount) -> Donation:
    """A holder gives from their own money into their held part: the same flow, with themselves as the donor."""
    amount = _amount(amount)
    if holder.status != Holder.ACTIVE:
        raise FundError(_("This holder cannot record a donation now."))
    with transaction.atomic():
        donation = Donation.objects.create(
            donor_member=holder.member, holder=holder, amount=amount, currency=holder.currency
        )
        _record(donation, amount)
        return donation
