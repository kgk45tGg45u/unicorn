"""Choosing few payers, in turn (docs/07 section 3, "Payers are few and take turns").

Banks watch for many small payments from strangers, so one payment is made by one holder, or at most
`tradefund.max_payers_per_request` of them. Holders who have paid least, compared with what they hold, go first.
"""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.rules.services import get_param

from . import books, trust
from .models import FundEntry, Holder, PaymentRequest

MIN_TRUST = Decimal("0.2")


def committed(holder) -> Decimal:
    """What the holder was already asked to pay and has not yet confirmed."""
    total = PaymentRequest.objects.filter(payer=holder, status__in=PaymentRequest.OPEN).aggregate(t=Sum("amount"))["t"]
    return total or Decimal("0.00")


def available(holder) -> Decimal:
    return books.free(holder) - committed(holder)


def paid_share(holder, now=None) -> Decimal:
    """Euros paid out in the last 12 months divided by (the average holding + 1)."""
    now = now or timezone.now()
    start = now - timedelta(days=365)
    entries = list(
        FundEntry.objects.filter(holder=holder, created_at__lte=now)
        .exclude(kind__in=books.RESERVE_KINDS)
        .values_list("created_at", "amount", "kind")
    )
    paid = sum((-a for c, a, k in entries if c >= start and k in ("payment_out", "transfer_out")), Decimal(0))
    samples = []
    for i in range(12):
        at = now - timedelta(days=30 * i)
        samples.append(sum((a for c, a, k in entries if c <= at), Decimal(0)))
    average = sum(samples, Decimal(0)) / 12
    return paid / (average + 1)


def choose_payers(amount, currency, exclude=()) -> list[tuple[Holder, Decimal]]:
    """The holders who should pay `amount`, with their parts. An empty list means: the fund cannot pay this now."""
    amount = Decimal(amount)
    excluded = {h.pk if hasattr(h, "pk") else h for h in exclude}
    candidates = []
    for h in Holder.objects.filter(status=Holder.ACTIVE, currency=currency).exclude(pk__in=excluded):
        room = available(h)
        if room > 0 and trust.score(h) >= MIN_TRUST:
            candidates.append((h, room))
    candidates.sort(key=lambda hr: (paid_share(hr[0]), -hr[1], hr[0].pk))
    for h, room in candidates:  # one payer, when one covers it
        if room >= amount:
            return [(h, amount)]
    largest = sorted(candidates, key=lambda hr: (-hr[1], hr[0].pk))[: get_param("tradefund.max_payers_per_request")]
    if sum((r for _h, r in largest), Decimal(0)) >= amount:
        parts, left = [], amount
        for h, room in largest:
            part = min(room, left)
            if part > 0:
                parts.append((h, part))
                left -= part
        return parts
    return []
