"""The trade fund's books: the euros each holder holds for the group (docs/07 section 4, HF-7).

Every change is a `FundEntry`, written only by `post_fund()`. The chain works like the UNIQ ledger's: the
`fund` head is locked, the hash covers the previous hash and the entry. The app never moves money (HF-12): an
entry records what people confirmed.
"""

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.hashing import chain_hash
from apps.core.money import cur
from apps.ledger.models import ChainHead

from . import fx
from .models import FundEntry, Holder

RESERVE_KINDS = ("reserve_mark", "reserve_unmark")
KINDS = {k for k, _label in FundEntry.KINDS}
REASON_KINDS = {k for k, _label in FundEntry.REASON_KINDS}
ZERO = Decimal("0.00")


class BooksError(ValueError):
    """The fund's books refuse this entry. The message is plain words."""


def _sum(qs):
    return qs.aggregate(t=Sum("amount"))["t"] or ZERO


def holding(holder, currency=None) -> Decimal:
    """Everything the holder holds for the group: free and reserve together."""
    qs = FundEntry.objects.filter(holder=holder).exclude(kind__in=RESERVE_KINDS)
    if currency:
        qs = qs.filter(currency=currency)
    return _sum(qs)


def reserve(holder, currency=None) -> Decimal:
    """The part of the holding that is marked as loss reserve."""
    qs = FundEntry.objects.filter(holder=holder)
    if currency:
        qs = qs.filter(currency=currency)
    return _sum(qs.filter(kind="reserve_mark")) - _sum(qs.filter(kind="reserve_unmark"))


def free(holder, currency=None) -> Decimal:
    return holding(holder, currency) - reserve(holder, currency)


def fund_total_eur(on=None) -> Decimal:
    """The whole fund in euros, at the rates of the day."""
    totals = {}
    for row in (
        FundEntry.objects.exclude(kind__in=RESERVE_KINDS).values("currency").annotate(t=Sum("amount")).order_by()
    ):
        totals[row["currency"]] = row["t"] or ZERO
    return cur(sum((fx.to_eur(t, c, on) for c, t in totals.items()), ZERO))


def _payload(e):
    return {
        "seq": e.seq,
        "holder": e.holder_id,
        "kind": e.kind,
        "amount": str(e.amount),
        "currency": e.currency,
        "reason": e.reason,
        "reason_kind": e.reason_kind,
        "ref_type": e.ref_type,
        "ref_id": e.ref_id,
        "created_at": e.created_at,
    }


def post_fund(holder, kind, amount, reason, reason_kind, ref=None, currency=None) -> FundEntry:
    """Write one entry in the fund's books. The only code allowed to create `FundEntry` rows."""
    if not (reason or "").strip():
        raise BooksError(_("Every entry in the fund's books needs a written reason."))  # HF-7
    if kind not in KINDS:
        raise BooksError(_("This kind of entry does not exist."))
    if reason_kind not in REASON_KINDS:
        raise BooksError(_("Please say whether this is a loan, a group purchase, a gift, a bill or internal."))
    amount = cur(amount)
    if amount == 0:
        raise BooksError(_("An entry cannot be zero."))
    if kind in RESERVE_KINDS and amount < 0:
        raise BooksError(_("A reserve entry must be more than zero."))
    if kind in ("setaside", "donation", "transfer_in") and amount < 0:
        raise BooksError(_("This kind of entry must raise the holding."))
    if kind in ("payment_out", "transfer_out") and amount > 0:
        raise BooksError(_("This kind of entry must lower the holding."))
    with transaction.atomic():
        head = ChainHead.objects.select_for_update().get(name="fund")  # serialises all entries
        holder = Holder.objects.select_for_update().get(pk=holder.pk)
        currency = currency or holder.currency
        if currency != holder.currency:
            raise BooksError(_("This holder holds in %(currency)s.") % {"currency": holder.currency})
        now_holding, now_reserve = holding(holder), reserve(holder)
        if kind == "reserve_unmark" and amount > now_reserve:
            raise BooksError(_("There is not that much in the reserve."))
        if kind == "reserve_mark":
            new_holding, new_reserve = now_holding, now_reserve + amount
        elif kind == "reserve_unmark":
            new_holding, new_reserve = now_holding, now_reserve - amount
        else:
            new_holding, new_reserve = now_holding + amount, now_reserve
        if new_holding - new_reserve < 0:
            raise BooksError(_("The free part of this holding cannot go below zero."))
        ref_type = ref_id = ""
        if isinstance(ref, tuple):
            ref_type, ref_id = str(ref[0]), str(ref[1])
        elif ref is not None:
            ref_type, ref_id = ref.__class__.__name__.lower(), str(ref.pk)
        seq = head.last_seq + 1
        entry = FundEntry(
            seq=seq,
            holder=holder,
            kind=kind,
            amount=amount,
            currency=currency,
            reason=reason.strip(),
            reason_kind=reason_kind,
            ref_type=ref_type,
            ref_id=ref_id,
            created_at=timezone.now(),
            prev_hash=head.last_hash,
        )
        entry.hash = chain_hash(head.last_hash, _payload(entry))
        entry.save()
        head.last_seq, head.last_hash = seq, entry.hash
        head.save(update_fields=["last_seq", "last_hash"])
        return entry


def audit_findings() -> list[str]:
    """For the nightly audit (P02.T07): the chain links, the hashes, and no holding below zero."""
    findings = []
    prev_hash, expected = "0" * 64, 1
    holdings, reserves = {}, {}
    last_seq, last_hash = 0, prev_hash
    for e in FundEntry.objects.order_by("seq"):
        if e.seq != expected:
            findings.append(_("Fund entry numbers jump from %(a)s to %(b)s.") % {"a": expected - 1, "b": e.seq})
        expected = e.seq + 1
        if e.prev_hash != last_hash:
            findings.append(_("Fund entry %(n)s does not link to the one before it.") % {"n": e.seq})
        if chain_hash(e.prev_hash, _payload(e)) != e.hash:
            findings.append(_("Fund entry %(n)s does not match its fingerprint.") % {"n": e.seq})
        last_seq, last_hash = e.seq, e.hash
        if e.kind == "reserve_mark":
            reserves[e.holder_id] = reserves.get(e.holder_id, ZERO) + e.amount
        elif e.kind == "reserve_unmark":
            reserves[e.holder_id] = reserves.get(e.holder_id, ZERO) - e.amount
        else:
            holdings[e.holder_id] = holdings.get(e.holder_id, ZERO) + e.amount
    head = ChainHead.objects.filter(name="fund").first()
    if head is None or (head.last_seq, head.last_hash) != (last_seq, last_hash):
        findings.append(_("The end of the fund's chain does not match its last entry."))
    for holder_id in set(holdings) | set(reserves):
        if holdings.get(holder_id, ZERO) - reserves.get(holder_id, ZERO) < 0:
            findings.append(_("Holder %(n)s holds less than zero.") % {"n": holder_id})
    return findings
