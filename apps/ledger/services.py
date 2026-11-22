from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.rules.services import get_param

from .models import Account, AccountBalance, Period

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
