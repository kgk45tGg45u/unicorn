from datetime import UTC, datetime
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from apps.ledger import services
from apps.ledger.models import Account, Period
from apps.members import services as member_services
from apps.members.models import Member, User

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def defaults():
    call_command("load_defaults", stdout=StringIO())


def test_only_one_fund1_and_one_fund2_exist():
    assert Account.objects.filter(kind="fund1").count() == 1
    assert Account.objects.filter(kind="fund2").count() == 1
    assert services.fund1().member is None and services.fund2().member is None


def test_verifying_a_member_opens_both_accounts():
    member = member_services.create_applicant(User.objects.create_user("a@x.org"), "Ada", "DE")
    for hook in member_services.VERIFIED_HOOKS:
        hook(member)
    assert services.member_account(member).kind == "member"
    assert services.retirement_account(member).kind == "retirement"


def test_verification_flow_calls_the_hook():
    from datetime import date

    voucher_a = member_services.create_applicant(User.objects.create_user("v1@x.org"), "v1", "DE")
    voucher_b = member_services.create_applicant(User.objects.create_user("v2@x.org"), "v2", "DE")
    helper = member_services.create_applicant(User.objects.create_user("h@x.org"), "h", "DE")
    for m in (voucher_a, voucher_b, helper):
        m.status = Member.MEMBER
        m.save()
    helper.is_identity_helper = True
    helper.save()
    new = member_services.create_applicant(User.objects.create_user("n@x.org"), "n", "DE")
    member_services.vouch(voucher_a, new, "a")
    member_services.vouch(voucher_b, new, "b")
    member_services.record_in_person_check(helper, new, date(2026, 11, 1), "Berlin")
    assert services.member_account(new)


def test_open_member_accounts_is_idempotent():
    member = member_services.create_applicant(User.objects.create_user("a@x.org"), "Ada", "DE")
    services.open_member_accounts(member)
    services.open_member_accounts(member)
    assert Account.objects.filter(member=member).count() == 2


def test_current_period_creates_the_month_once():
    now = datetime(2026, 3, 15, 12, tzinfo=UTC)
    p1 = services.current_period(now)
    p2 = services.current_period(now)
    assert p1.pk == p2.pk and (p1.year, p1.month) == (2026, 3)
    assert Period.objects.count() == 1
    assert p1.tax_rate == Decimal("0.2")


def test_period_uses_berlin_month():
    # 23:30 UTC on 31 Jan is already 1 Feb in Berlin
    p = services.current_period(datetime(2026, 1, 31, 23, 30, tzinfo=UTC))
    assert (p.year, p.month) == (2026, 2)


def test_new_period_takes_previous_next_tax_rate():
    p1 = services.current_period(datetime(2026, 3, 15, tzinfo=UTC))
    p1.next_tax_rate = Decimal("0.2500")
    p1.save()
    p2 = services.current_period(datetime(2026, 4, 2, tzinfo=UTC))
    assert p2.tax_rate == Decimal("0.2500")
