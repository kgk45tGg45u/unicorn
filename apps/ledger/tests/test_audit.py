from decimal import Decimal

import pytest
from django.db import connection

from apps.core.models import AuditEvent
from apps.ledger import services
from apps.ledger.audit import run_audit
from apps.ledger.models import AccountBalance
from apps.ledger.services import Leg, post
from apps.members import services as ms
from apps.members.models import User

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture
def books():
    m = ms.create_applicant(User.objects.create_user("a@x.org"), "a", "DE")
    services.open_member_accounts(m)
    acc = services.member_account(m)
    post("hours_pay", "h", [Leg(services.fund2(), D(-5)), Leg(acc, D(5))])
    post("purchase", "p", [Leg(acc, D(-2)), Leg(services.fund1(), D(2))])
    return m


def real_findings(run):
    return [f for f in run.findings if not f.startswith("Warning:")]


def test_an_untouched_ledger_passes(books):
    run = run_audit()
    assert run.ok and not real_findings(run) and run.last_seq == 2


def test_incremental_audit_continues_after_last_run(books):
    run_audit()
    post("hours_pay", "more", [Leg(services.fund2(), D(-1)), Leg(services.member_account(books), D(1))])
    run = run_audit()
    assert run.ok and run.last_seq == 3 and not run.full


def test_a_broken_account_balance_is_found(books):
    acc = services.member_account(books)
    with connection.cursor() as cursor:  # AccountBalance is not append-only, so a raw change works
        cursor.execute("UPDATE ledger_accountbalance SET balance = 99 WHERE account_id = %s", [acc.pk])
    run = run_audit()
    assert not run.ok
    assert any("does not match its entries" in f for f in run.findings)
    assert AuditEvent.objects.filter(verb="audit_failed").exists()


def test_a_tampered_chain_head_is_found(books):
    from apps.ledger.models import ChainHead

    ChainHead.objects.filter(name="uniq").update(last_hash="f" * 64)
    assert not run_audit(full=True).ok


def test_sums_are_checked(books):
    assert AccountBalance.objects.count() >= 4
    assert run_audit(full=True).ok
