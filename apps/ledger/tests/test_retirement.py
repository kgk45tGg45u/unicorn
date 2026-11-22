from decimal import Decimal

import pytest
from allauth.account.models import EmailAddress
from django.urls import reverse

from apps.ledger import services
from apps.ledger.audit import run_audit
from apps.ledger.services import LedgerError, Leg, post
from apps.members import services as ms
from apps.members.models import User

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture
def m():
    member = ms.create_applicant(User.objects.create_user("a@x.org"), "a", "DE")
    services.open_member_accounts(member)
    post("hours_pay", "h", [Leg(services.fund2(), D(-120)), Leg(services.member_account(member), D(120))])
    return member


def test_moving_in_works(m):
    services.to_retirement(m, D(100))
    assert services.balance(services.retirement_account(m)) == 100
    assert services.balance(services.member_account(m)) == 20


def test_moving_in_more_than_available_fails(m):
    with pytest.raises(LedgerError):
        services.to_retirement(m, D(500))


def test_the_early_withdrawal_limit_holds(m):
    services.to_retirement(m, D(100))
    # no balance existed at the start of the month, so nothing may be taken out this month
    with pytest.raises(LedgerError, match="only a part"):
        services.from_retirement(m, D(1))


def test_withdrawal_up_to_the_limit_after_pension_age(m, monkeypatch):
    services.to_retirement(m, D(100))
    monkeypatch.setattr("apps.members.services.has_reached_pension_age", lambda member: True)
    services.from_retirement(m, D(60))
    assert services.balance(services.retirement_account(m)) == 40


def test_limit_counts_the_start_of_month_balance(m):
    from apps.ledger.models import Entry, Period, Transaction
    from apps.rules.services import get_param

    # a balance of 100 existed before this month: put the deposit into an earlier period
    old = Period.objects.create(year=2020, month=1, tax_rate=D("0.2"), status="open")
    post(
        "retirement_in",
        "old",
        [Leg(services.member_account(m), D(-100)), Leg(services.retirement_account(m), D(100))],
        period=old,
    )
    limit = D(100) * get_param("economy.retirement.early_withdrawal_max_share_per_month")
    services.from_retirement(m, limit - D("0.0100"))
    with pytest.raises(LedgerError):
        services.from_retirement(m, D("0.0200"))
    assert Entry.objects.count() and Transaction.objects.count()


def test_hf08_retirement_balance_is_still_the_members_in_the_audit_sums(m):
    services.to_retirement(m, D(50))
    run = run_audit(full=True)
    assert run.ok
    assert services.balance(services.retirement_account(m)) == 50


def test_forms_need_recent_authentication(client, m):
    EmailAddress.objects.create(user=m.user, email=m.user.email, verified=True, primary=True)
    client.force_login(m.user)
    assert client.get(reverse("ledger:retirement")).status_code == 200
    response = client.post(reverse("ledger:retirement"), {"amount": "1", "direction": "in"})
    assert response.status_code == 302 and "reauthenticate" in response.url
    assert services.balance(services.retirement_account(m)) == 0
