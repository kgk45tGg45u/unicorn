"""The UNIQ identities that must be exact (docs/03 sections 2-3: book 4-6 and 4-7, HF-1, HF-6)."""

from decimal import Decimal

from django.db.models import Q, Sum
from django.utils.translation import gettext as _

from apps.ledger.models import Account, Entry

ZERO = Decimal("0.0000")


def _sum(qs):
    return qs.aggregate(t=Sum("amount"))["t"] or ZERO


def _up_to(period):
    """Entries of this period and every earlier one."""
    return Entry.objects.filter(
        Q(transaction__period__year__lt=period.year)
        | Q(transaction__period__year=period.year, transaction__period__month__lte=period.month)
    )


def balances(period) -> dict:
    """Balances at the end of the period, by kind of account."""
    rows = _up_to(period)
    return {
        "members": _sum(rows.filter(account__kind=Account.MEMBER)),
        "retirement": _sum(rows.filter(account__kind=Account.RETIREMENT)),
        "fund1": _sum(rows.filter(account__kind=Account.FUND1)),
        "fund2": _sum(rows.filter(account__kind=Account.FUND2)),
    }


def check_uniq_identities(period, flows) -> dict[str, Decimal]:
    """Each value must be exactly 0. `flows` comes from `accounts.flows(period)`."""
    in_period = Entry.objects.filter(transaction__period=period)
    delta_households = _sum(in_period.filter(account__kind__in=(Account.MEMBER, Account.RETIREMENT)))
    delta_fund2 = _sum(in_period.filter(account__kind=Account.FUND2))
    now = balances(period)
    start_fund1 = now["fund1"] - _sum(in_period.filter(account__kind=Account.FUND1))
    return {
        # 4-6: (gross hours pay + transfers) - (change in member and retirement balances + spent + tax)
        "households": flows["hours_paid"] + flows["transfers"] - (delta_households + flows["spent"] + flows["tax"]),
        # 4-7: (hours pay + transfers) - tax - cancelled - change in what Fund 2 has issued
        "fund2": flows["hours_paid"] + flows["transfers"] - flows["tax"] - flows["cancelled"] - (-delta_fund2),
        # Fund 1: what it had and received, less what was cancelled, is what is left (0 after the close: HF-6)
        "fund1": start_fund1 + flows["spent"] - flows["cancelled"] - now["fund1"],
        "fund1_after_close": now["fund1"],
        # conservation: outstanding = members + retirement + Fund 1
        "conservation": -now["fund2"] - (now["members"] + now["retirement"] + now["fund1"]),
    }


def failures(result) -> dict[str, str]:
    return {k: str(v) for k, v in result.items() if v != 0}


WORDS = {
    "households": _("What members earned does not equal what they kept, spent and paid in tax."),
    "fund2": _("Fund 2's issues and takings do not add up."),
    "fund1": _("Fund 1 did not receive what members spent."),
    "fund1_after_close": _("Fund 1 is not zero after the close."),
    "conservation": _("The UNIQ outstanding do not equal the sum of the accounts."),
}
