"""The trust rating and the caps (docs/07 section 5, HF-11).

HF-11: the rating only limits how many euros a member may hold for the trade fund. It never touches work, pay, votes
or prices. It is computed from the fund's records only. No module outside `apps/tradefund/` imports this one.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.money import cur
from apps.core.notify import notify
from apps.rules.services import get_param

from . import books, fx
from .models import FundEntry, Holder, PaymentRequest, TrustEvent

DELTA_PARAMS = {
    "on_time": "tradefund.trust.on_time",
    "monthly": "tradefund.trust.monthly",
    "late": "tradefund.trust.late",
    "missed": "tradefund.trust.missed",
    "mismatch": "tradefund.trust.mismatch",
}
Q4 = Decimal("0.0001")


def score(holder) -> Decimal:
    total = sum((e.delta for e in TrustEvent.objects.filter(holder=holder)), Decimal(0))
    return min(max(total, Decimal(0)), Decimal(1)).quantize(Q4)


def start(holder) -> TrustEvent:
    """The first event of a holder: the starting score (founders start higher)."""
    key = "tradefund.trust.founders_start" if holder.member.is_founder else "tradefund.trust.start"
    return TrustEvent.objects.create(holder=holder, kind="start", delta=get_param(key), note=_("Start as a holder."))


def record(holder, kind, ref="", note="") -> TrustEvent:
    """Add an event. `left_without_handover` takes the score to zero."""
    if kind == "left_without_handover":
        delta = -score(holder)
    elif kind in DELTA_PARAMS:
        delta = get_param(DELTA_PARAMS[kind])
    else:
        raise ValueError(kind)
    event = TrustEvent.objects.create(holder=holder, kind=kind, delta=delta, ref=str(ref), note=note[:300])
    audit.record("system", "trust.event", event, kind=kind, holder=holder.member.number)
    return event


def cap_eur(holder, on=None) -> Decimal:
    """The most the holder may hold, in euros: base + score x (max_cap - base)."""
    base = get_param("tradefund.base_cap_eur")
    max_cap = max(base, books.fund_total_eur(on) * get_param("tradefund.holder_max_share"))
    return (base + score(holder) * (max_cap - base)).quantize(Decimal("0.01"))


def holding_eur(holder, on=None) -> Decimal:
    return fx.to_eur(books.holding(holder), holder.currency, on)


def room_eur(holder) -> Decimal:
    return cap_eur(holder) - holding_eur(holder)


def month_key(year, month) -> str:
    return f"{year}-{month:02d}"


def run_monthly(month: date | None = None) -> int:
    """Give `monthly` to each active holder without a late, missed or mismatch event in the month (default: the last
    full month). Safe to run twice: each holder gets one `monthly` per month."""
    if month is None:
        month = (timezone.localdate().replace(day=1) - timedelta(days=1)).replace(day=1)
    key = month_key(month.year, month.month)
    next_month = (month + timedelta(days=32)).replace(day=1)
    given = 0
    for holder in Holder.objects.filter(status=Holder.ACTIVE):
        if timezone.localtime(holder.joined_at).date() >= next_month:
            continue  # was not yet a holder that month
        if TrustEvent.objects.filter(holder=holder, kind="monthly", ref=key).exists():
            continue
        if TrustEvent.objects.filter(
            holder=holder,
            kind__in=("late", "missed", "mismatch"),
            created_at__year=month.year,
            created_at__month=month.month,
        ).exists():
            continue
        record(holder, "monthly", ref=key, note=_("A month as a holder without problems."))
        given += 1
    return given


# --- Above the cap ---


def move_excess(now=None) -> int:
    """A holder who holds more than their cap gets a request to pass the excess to the holder with most room."""
    from . import payments

    made = 0
    for holder in Holder.objects.filter(status=Holder.ACTIVE):
        over = holding_eur(holder) - cap_eur(holder)
        if over <= 0:
            continue
        free = books.free(holder)
        excess = min(cur(fx.from_eur(over, holder.currency)), free)
        if excess <= 0:
            continue
        if PaymentRequest.objects.filter(
            payer=holder, purpose="over_cap", status__in=PaymentRequest.OPEN
        ).exists():  # one request at a time
            continue
        candidates = [
            h
            for h in Holder.objects.filter(status=Holder.ACTIVE, currency=holder.currency).exclude(pk=holder.pk)
            if room_eur(h) > 0
        ]
        if not candidates:
            continue
        target = max(candidates, key=room_eur)
        room = cur(fx.from_eur(room_eur(target), target.currency))
        payments.request_payment(
            payer=holder,
            amount=min(excess, room),
            currency=holder.currency,
            reason_kind="internal",
            payee_holder=target,
            description=_("Passing on euros above the cap."),
            purpose="over_cap",
        )
        made += 1
    return made


# --- The loss reserve ---


def mark_reserve(amount, currency, ref, why) -> list:
    """Mark the reserve share of an amount that came in, on the holders with the highest trust that have room."""
    return mark_reserve_amount(cur(Decimal(amount) * get_param("tradefund.loss_reserve_share")), currency, ref, why)


def mark_reserve_amount(share, currency, ref, why) -> list:
    """Mark exactly `share` as loss reserve, on the holders with the highest trust that have free euros."""
    marked = []
    if share <= 0:
        return marked
    holders = sorted(Holder.objects.filter(status=Holder.ACTIVE, currency=currency), key=lambda h: (-score(h), h.pk))
    left = share
    for h in holders:
        chunk = min(left, books.free(h))
        if chunk <= 0:
            continue
        marked.append(books.post_fund(h, "reserve_mark", chunk, why, "internal", ref=ref))
        left -= chunk
        if left <= 0:
            break
    return marked


def reserve_total(currency) -> Decimal:
    return sum((books.reserve(h) for h in Holder.objects.filter(currency=currency)), Decimal(0))


def cover_from_reserve(request) -> list:
    """Pay a missed or stolen amount from the loss reserve: new payment requests from the holders who keep it.

    Returns the new requests, or [] when the reserve is too small (then the purchase waits and its ticket says so).
    """
    from . import payments

    with transaction.atomic():
        holders = sorted(
            Holder.objects.filter(status=Holder.ACTIVE, currency=request.currency).exclude(pk=request.payer_id),
            key=lambda h: -books.reserve(h),
        )
        remaining, plan = request.amount, []
        for h in holders[: get_param("tradefund.max_payers_per_request")]:
            part = min(remaining, books.reserve(h))
            if part > 0:
                plan.append((h, part))
                remaining -= part
        if remaining > 0:
            return []
        created = []
        for h, part in plan:
            books.post_fund(
                h,
                "reserve_unmark",
                part,
                _("The loss reserve covers a missed payment (payment request %(id)s).") % {"id": request.pk},
                "internal",
                ref=request,
            )
            created.append(
                payments.request_payment(
                    payer=h,
                    amount=part,
                    currency=request.currency,
                    reason_kind=request.reason_kind,
                    ticket=request.ticket,
                    mandate=request.mandate,
                    payee_holder=request.payee_holder,
                    payee_member=request.payee_member,
                    payee_external=request.payee_external,
                    confirmer=request.confirmer,
                    description=request.description,
                    purpose=request.purpose,
                    ref=(request.ref_type, request.ref_id) if request.ref_type else None,
                    replaces=request,
                )
            )
        audit.record("system", "reserve.covered", request, parts=len(created))
        return created


def write_off(holder, why) -> FundEntry | None:
    """A holder left or vanished with the group's euros: take their holding out of the books, and let the reserve
    absorb it (the reserve marks of other holders shrink by the same amount, as far as they reach)."""
    with transaction.atomic():
        amount = books.holding(holder)
        if amount <= 0:
            return None
        if books.reserve(holder):
            books.post_fund(holder, "reserve_unmark", books.reserve(holder), why, "internal")
        entry = books.post_fund(holder, "correction", -amount, why, "internal")
        left = amount
        for h in sorted(Holder.objects.exclude(pk=holder.pk), key=lambda h: -books.reserve(h)):
            part = min(left, books.reserve(h))
            if part > 0:
                books.post_fund(h, "reserve_unmark", part, why, "internal", ref=entry)
                left -= part
            if left <= 0:
                break
        return entry


# --- Contesting an event ---


def annul(event, note="") -> TrustEvent:
    """Add an `annulled` event with the opposite delta (docs/07 section 5). Events are never changed."""
    if TrustEvent.objects.filter(kind="annulled", ref=f"event:{event.pk}").exists():
        raise ValueError(_("This event was already annulled."))
    if event.kind in ("start", "annulled"):
        raise ValueError(_("This event cannot be annulled."))
    return TrustEvent.objects.create(
        holder=event.holder, kind="annulled", delta=-event.delta, ref=f"event:{event.pk}", note=note[:300]
    )


def notify_holder(holder, text, url="/fund/trust/"):
    notify(holder.member, text, url)


# --- Contesting an event: the trust review group decides (docs/07 section 5) ---


class TrustError(ValueError):
    """A plain-words reason why a trust action cannot be done."""


def can_contest(event) -> bool:
    if event.kind in ("start", "annulled"):
        return False
    if TrustEvent.objects.filter(kind="annulled", ref=f"event:{event.pk}").exists():
        return False
    from apps.tickets.models import Ticket

    return not Ticket.objects.filter(
        type="trust_review", action_payload__event_id=event.pk, status__in=("open", "confirming", "panel", "approved")
    ).exists()


def contest(event, member, why):
    """Open a `trust_review` ticket for the event. The elected trust review group decides it by majority."""
    from apps.tickets import services as ticket_services
    from apps.tickets.briefs import _check

    if event.holder.member_id != member.pk:
        raise TrustError(_("You can only contest events of your own rating."))
    if not can_contest(event):
        raise TrustError(_("This event cannot be contested, or it is already being looked at."))
    why = (why or "").strip()
    if len(why) < 10:
        raise TrustError(_("Please say in a few words why the event is wrong."))
    kinds = [str(label) for k, label in TrustEvent.KINDS if k not in ("start", "annulled", event.kind)]
    check = _check(
        _("What kind of event is contested?"), str(event.get_kind_display()), kinds[:2], _("the first sentence")
    )
    brief = _(
        "A holder contests an event in their trust rating: %(kind)s on %(date)s (%(delta)s). The note says: "
        '"%(note)s". The holder says: "%(why)s". Yes means the event is annulled. No means it stays.'
    ) % {
        "kind": event.get_kind_display(),
        "date": timezone.localtime(event.created_at).date(),
        "delta": event.delta,
        "note": event.note,
        "why": why[:500],
    }
    return ticket_services.create_ticket(
        "trust_review",
        member,
        _("Contest of a trust event"),
        brief=brief,
        check=check,
        action_payload={"event_id": event.pk},
    )


def _annul_action(ticket):
    event = TrustEvent.objects.get(pk=ticket.action_payload["event_id"])
    annul(event, _("Annulled by the trust review group (%(number)s).") % {"number": ticket.number})
    notify_holder(event.holder, _("An event in your trust rating was annulled."))
    return {"annulled": event.pk}


def register():
    from apps.tickets import actions

    actions.register(
        "annul_trust_event",
        _annul_action,
        lambda p: [] if p.get("event_id") else [_("This ticket does not say what it is about.")],
    )
