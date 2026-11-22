from dataclasses import dataclass
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.hashing import chain_hash
from apps.core.money import minutes_to_uniq, uniq
from apps.rules.services import get_param

from .models import Account, AccountBalance, ChainHead, Entry, Hold, Period, Transaction

BERLIN = ZoneInfo("Europe/Berlin")


class LedgerError(ValueError):
    """The books refuse this posting. The message is plain words."""


def _account(kind, member=None):
    account = Account.objects.filter(kind=kind, member=member).first()
    if account is None:
        raise LedgerError(f"The {kind} account does not exist.")
    return account


def fund1():
    return _account(Account.FUND1)


def fund2():
    return _account(Account.FUND2)


def member_account(member):
    return _account(Account.MEMBER, member)


def retirement_account(member):
    return _account(Account.RETIREMENT, member)


def open_member_accounts(member):
    """Open the member's UNIQ account and retirement account. Safe to run twice."""
    accounts = []
    for kind in (Account.MEMBER, Account.RETIREMENT):
        try:
            with transaction.atomic():
                account, _created = Account.objects.get_or_create(kind=kind, member=member)
        except IntegrityError:
            account = Account.objects.get(kind=kind, member=member)
        AccountBalance.objects.get_or_create(account=account)
        accounts.append(account)
    return accounts


def current_period(now=None):
    """The period of `now` in Europe/Berlin; created as `open` if missing."""
    local = (now or timezone.now()).astimezone(BERLIN)
    period = Period.objects.filter(year=local.year, month=local.month).first()
    if period is not None:
        return period
    previous = Period.objects.order_by("-year", "-month").first()
    if previous is not None and previous.next_tax_rate is not None:
        rate = previous.next_tax_rate
    else:
        rate = get_param("economy.flat_tax.start_rate")
    try:
        with transaction.atomic():
            return Period.objects.create(year=local.year, month=local.month, tax_rate=rate)
    except IntegrityError:
        return Period.objects.get(year=local.year, month=local.month)


# --- The one way to move UNIQ ---


@dataclass(frozen=True)
class Leg:
    account: Account
    amount: Decimal


def balance(account) -> Decimal:
    row = AccountBalance.objects.filter(account=account).first()
    return row.balance if row else Decimal("0.0000")


def _held(account) -> Decimal:
    total = Hold.objects.filter(account=account, status=Hold.ACTIVE).aggregate(t=Sum("amount"))["t"]
    return total or Decimal("0.0000")


def available(account) -> Decimal:
    """Balance minus active holds."""
    return balance(account) - _held(account)


def _ref_parts(ref):
    if ref is None:
        return "", ""
    if isinstance(ref, tuple):
        return str(ref[0]), str(ref[1])
    return ref.__class__.__name__.lower(), str(ref.pk)


# kind -> (kinds of the debited accounts, kinds of the credited accounts)
PATTERNS = {
    "hours_pay": ({Account.FUND2}, {Account.MEMBER}),  # HF-1
    "transfer": ({Account.FUND2}, {Account.MEMBER}),  # HF-1
    "tax": ({Account.MEMBER}, {Account.FUND2}),
    "purchase": ({Account.MEMBER}, {Account.FUND1}),
    "rent": ({Account.MEMBER}, {Account.FUND1}),
    "retirement_in": ({Account.MEMBER}, {Account.RETIREMENT}),
    "retirement_out": ({Account.RETIREMENT}, {Account.MEMBER}),
    "cancel": ({Account.FUND1}, {Account.FUND2}),  # HF-6: Fund 1 is only debited by a cancel
}


def post(kind, reason, legs, *, ref=None, actor_ref="system", period=None, capturing_hold=None):
    """Post a balanced transaction. The only code allowed to create Transaction or Entry rows."""
    if not (reason or "").strip():
        raise LedgerError("Every transfer needs a written reason")  # HF-7
    if kind not in PATTERNS and kind != "correction":
        raise LedgerError(f"Unknown kind of transaction: {kind}")
    legs = [Leg(leg.account, uniq(leg.amount)) for leg in legs]
    if len(legs) < 2:
        raise LedgerError("A transaction needs at least two legs")
    if any(leg.amount == 0 for leg in legs):
        raise LedgerError("A leg cannot be zero")
    if sum((leg.amount for leg in legs), Decimal("0")) != 0:
        raise LedgerError("The legs must add up to zero")

    with transaction.atomic():
        period = period or current_period()
        period.refresh_from_db()
        if period.status != Period.OPEN and not (kind == "cancel" and period.status == Period.CLOSING):
            raise LedgerError("This period is closed")

        # HF-5: UNIQ never move between members.
        members = {leg.account.member_id for leg in legs if leg.account.kind in (Account.MEMBER, Account.RETIREMENT)}
        if len(members) > 1:
            raise LedgerError("UNIQ never move between members")

        ref_type, ref_id = _ref_parts(ref)
        if kind == "correction":
            _check_correction(legs, ref)
        else:
            debit_kinds, credit_kinds = PATTERNS[kind]
            if any(leg.amount < 0 and leg.account.kind not in debit_kinds for leg in legs) or any(
                leg.amount > 0 and leg.account.kind not in credit_kinds for leg in legs
            ):
                raise LedgerError(f"A {kind} cannot move UNIQ between these accounts")

        head = ChainHead.objects.select_for_update().get(name="uniq")  # serialises all postings

        balances = {}
        for leg in sorted(legs, key=lambda x: x.account.pk):
            row = AccountBalance.objects.select_for_update().get_or_create(account=leg.account)[0]
            balances[leg.account.pk] = row
        for leg in legs:
            if leg.amount < 0 and leg.account.kind in (Account.MEMBER, Account.RETIREMENT):
                row = balances[leg.account.pk]
                debit = -sum((x.amount for x in legs if x.account.pk == leg.account.pk), Decimal("0"))
                if row.balance - debit < 0:
                    raise LedgerError("Not enough UNIQ available")
                held = _held(leg.account)
                if capturing_hold is not None and capturing_hold.account_id == leg.account.pk:
                    held -= capturing_hold.amount
                if row.balance - held - debit < 0:
                    raise LedgerError("Not enough UNIQ available")

        seq = head.last_seq + 1
        now = timezone.now()
        local = period
        payload = {
            "seq": seq,
            "period": f"{local.year}-{local.month:02d}",
            "kind": kind,
            "reason": reason.strip(),
            "ref_type": ref_type,
            "ref_id": ref_id,
            "actor_ref": actor_ref,
            "created_at": now,
            "entries": [
                {"account": leg.account.pk, "amount": str(leg.amount)}
                for leg in sorted(legs, key=lambda x: x.account.pk)
            ],
        }
        new_hash = chain_hash(head.last_hash, payload)
        tx = Transaction.objects.create(
            seq=seq,
            period=period,
            kind=kind,
            reason=reason.strip(),
            ref_type=ref_type,
            ref_id=ref_id,
            actor_ref=actor_ref,
            created_at=now,
            prev_hash=head.last_hash,
            hash=new_hash,
        )
        for leg in sorted(legs, key=lambda x: x.account.pk):
            Entry.objects.create(transaction=tx, account=leg.account, amount=leg.amount)
        for leg in legs:
            row = balances[leg.account.pk]
            row.balance += leg.amount
        for row in balances.values():
            row.save(update_fields=["balance"])
        head.last_seq = seq
        head.last_hash = new_hash
        head.save(update_fields=["last_seq", "last_hash"])
        return tx


def _check_correction(legs, ref):
    original = ref if isinstance(ref, Transaction) else None
    if original is None:
        raise LedgerError("A correction must refer to the transaction it corrects")
    if Transaction.objects.filter(kind="correction", ref_type="transaction", ref_id=str(original.pk)).exists():
        raise LedgerError("This transaction has already been corrected")
    expected = sorted((e.account_id, -e.amount) for e in original.entries.all())
    given = sorted((leg.account.pk, leg.amount) for leg in legs)
    if expected != given:
        raise LedgerError("A correction must be the exact opposite of the transaction it corrects")


def pay_hours_legs(member, minutes, tax_rate):
    """The legs for `hours_pay` (gross) and for `tax` on those hours."""
    gross = minutes_to_uniq(minutes)
    tax = uniq(gross * Decimal(str(tax_rate)))
    account = member_account(member)
    gross_legs = [Leg(fund2(), -gross), Leg(account, gross)]
    tax_legs = [Leg(account, -tax), Leg(fund2(), tax)] if tax else []
    return gross_legs, tax_legs


# --- Holds ---


def place_hold(member, amount, reason, ref=None):
    """Reserve UNIQ for an order or booking. Needs enough available UNIQ."""
    from apps.core import audit

    amount = uniq(amount)
    if amount <= 0:
        raise LedgerError("A hold must be more than zero")
    if not (reason or "").strip():
        raise LedgerError("A hold needs a written reason")
    with transaction.atomic():
        account = member_account(member)
        AccountBalance.objects.select_for_update().get_or_create(account=account)
        if available(account) < amount:
            raise LedgerError("Not enough UNIQ available")
        ref_type, ref_id = _ref_parts(ref)
        hold = Hold.objects.create(
            account=account, amount=amount, reason=reason.strip(), ref_type=ref_type, ref_id=ref_id
        )
        audit.record(member.number, "hold.placed", hold, amount=str(amount))
        return hold


def _lock_active(hold):
    hold = Hold.objects.select_for_update().get(pk=hold.pk)
    if hold.status != Hold.ACTIVE:
        raise LedgerError("This hold is already closed")
    return hold


def capture_hold(hold, reason, kind="purchase"):
    """Turn a hold into a purchase (member to Fund 1) and close it."""
    from apps.core import audit

    with transaction.atomic():
        hold = _lock_active(hold)
        tx = post(
            kind,
            reason,
            [Leg(hold.account, -hold.amount), Leg(fund1(), hold.amount)],
            ref=(hold.ref_type, hold.ref_id) if hold.ref_type else hold,
            actor_ref=hold.account.member.number,
            capturing_hold=hold,
        )
        hold.status = Hold.CAPTURED
        hold.closed_at = timezone.now()
        hold.save(update_fields=["status", "closed_at"])
        audit.record(hold.account.member.number, "hold.captured", hold, transaction=tx.seq)
        return tx


def release_hold(hold, reason):
    from apps.core import audit

    if not (reason or "").strip():
        raise LedgerError("Releasing a hold needs a written reason")
    with transaction.atomic():
        hold = _lock_active(hold)
        hold.status = Hold.RELEASED
        hold.closed_at = timezone.now()
        hold.save(update_fields=["status", "closed_at"])
        audit.record(hold.account.member.number, "hold.released", hold, reason=reason)
        return hold
