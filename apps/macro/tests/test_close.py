from decimal import Decimal

import pytest
from django.db import connection
from django.utils import timezone

from apps.ledger import services as ledger
from apps.ledger.models import Entry, Period, Transaction
from apps.macro import accounts, close, identities
from apps.macro.models import MacroSnapshot
from apps.tickets.models import Ticket

from .test_accounts import a_small_month

pytestmark = pytest.mark.django_db
D = Decimal


def this_month():
    now = timezone.localdate()
    return now.year, now.month


def test_a_full_month_closes():
    a_small_month()
    year, month = this_month()
    snap = close.close_period(year, month)
    period = Period.objects.get(year=year, month=month)
    assert snap is not None and period.status == "closed" and period.closed_at is not None
    assert snap.spent == D("1.2850") and snap.cancelled == D("1.2850")
    assert snap.outstanding == -ledger.balance(ledger.fund2())
    assert all(Decimal(v) == 0 for v in snap.identities.values())
    assert snap.lights and "unspent" in snap.lights and snap.lights["street_price"]["color"] == "grey"


def test_hf06_fund1_zero_after_close():
    a_small_month()
    assert ledger.balance(ledger.fund1()) > 0
    close.close_period(*this_month())
    assert ledger.balance(ledger.fund1()) == 0
    cancel = Transaction.objects.get(kind="cancel")
    assert cancel.reason == f"Period {cancel.period} closed: Fund 1 cancelled"


def test_hf01_issued_equals_hours_plus_transfers():
    a_small_month()
    snap = close.close_period(*this_month())
    issued = -Entry.objects.filter(
        transaction__period=snap.period, transaction__kind__in=("hours_pay", "transfer"), account__kind="fund2"
    ).aggregate(t=__import__("django.db.models", fromlist=["Sum"]).Sum("amount"))["t"]
    assert issued == snap.hours_paid + snap.transfers


def test_running_the_close_twice_changes_nothing():
    a_small_month()
    first = close.close_period(*this_month())
    count = Transaction.objects.count()
    again = close.close_period(*this_month())
    assert again.pk == first.pk and Transaction.objects.count() == count
    assert MacroSnapshot.objects.count() == 1


def test_the_next_period_gets_the_computed_tax_rate():
    a_small_month()
    year, month = this_month()
    snap = close.close_period(year, month)
    nxt_year, nxt_month = (year + 1, 1) if month == 12 else (year, month + 1)
    nxt = Period.objects.get(year=nxt_year, month=nxt_month)
    assert nxt.tax_rate == snap.tax_rate_next == Period.objects.get(year=year, month=month).next_tax_rate
    assert nxt.planned_hours > 0
    assert snap.tax_inputs["method"] == "balance_monthly" and "H" in snap.tax_inputs


def test_nothing_happened_means_nothing_to_close():
    assert close.close_period(2020, 1) is None


def test_a_forced_inconsistency_is_detected_and_blocks_the_close():
    a_small_month()
    year, month = this_month()
    period = Period.objects.get(year=year, month=month)
    tx = Transaction.objects.filter(period=period, kind="hours_pay").first()
    member_account = Entry.objects.filter(transaction=tx, account__kind="member").first().account
    Entry.objects.create(transaction=tx, account=member_account, amount=D("5.0000"))  # created behind post()'s back
    snap = close.close_period(year, month)
    period.refresh_from_db()
    assert period.status == "closing"
    assert any(Decimal(v) != 0 for v in snap.identities.values())
    ticket = Ticket.objects.get(type="audit_failure", title__contains=f"{year}-{month:02d}")
    assert "do not add up" in ticket.title
    from apps.members.models import Member

    auditor = Member.objects.first()
    close.acknowledge(period, auditor)
    period.refresh_from_db()
    assert period.status == "closed"
    assert connection and identities and accounts
