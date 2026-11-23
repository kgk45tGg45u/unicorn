from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.ledger import services as ledger
from apps.macro import close, retirement
from apps.macro.models import RetirementPlan
from apps.market.tests.conftest import fund
from apps.members import services as ms
from apps.tickets.models import Notification
from apps.units.tests.conftest import make_member

pytestmark = pytest.mark.django_db
D = Decimal
AMBER = {"unspent": {"color": "amber"}}


def test_suggestions_go_out_only_when_the_light_is_amber_or_red():
    m = make_member("m@x.org", "M")
    fund(m, 10)
    period = ledger.current_period()
    assert retirement.suggest(period, {"unspent": {"color": "green"}}) == 0
    assert retirement.suggest(period, {"unspent": {"color": "grey"}}) == 0
    assert not Notification.objects.filter(member=m).exists()
    assert retirement.suggest(period, AMBER) == 1
    note = Notification.objects.get(member=m)
    assert "5.0000 UNIQ" in note.text and note.url == "/me/retirement/?amount=5.0000"  # half of the excess
    assert retirement.suggest(period, AMBER) == 0  # once a month


def test_hf08_nothing_moves_without_the_member():
    m = make_member("m@x.org", "M")
    fund(m, 10)
    before = (ledger.balance(ledger.member_account(m)), ledger.balance(ledger.retirement_account(m)))
    retirement.suggest(ledger.current_period(), AMBER)
    retirement.pay_plans()
    assert (ledger.balance(ledger.member_account(m)), ledger.balance(ledger.retirement_account(m))) == before


def test_the_suggestion_can_be_switched_off():
    from apps.rules.models import Parameter

    fund(make_member("m@x.org", "M"), 10)
    Parameter.objects.filter(key="economy.retirement.suggest_on_alarm").update(value=False)
    assert retirement.suggest(ledger.current_period(), AMBER) == 0


def test_a_close_with_an_amber_light_only_notifies():
    m = make_member("m@x.org", "M")
    fund(m, 10)
    from apps.rules.models import Parameter

    Parameter.objects.filter(key="alarms.unspent_uniq_amber_months").update(value=0.0001)
    from apps.market.tests.conftest import World

    World()
    close.close_period(timezone.localdate().year, timezone.localdate().month)
    assert ledger.balance(ledger.retirement_account(m)) == 0


def test_the_payout_plan_pays_equal_parts_after_pension_age():
    m = make_member("m@x.org", "M")
    fund(m, 240)
    ledger.to_retirement(m, D(240))
    with pytest.raises(ledger.LedgerError):
        retirement.start_plan(m)  # not at pension age yet
    ms.set_private(m, birth_date="1950-01-01")
    plan = retirement.start_plan(m)
    assert plan.active
    today = timezone.localdate()
    assert retirement.pay_plans(today) == 1
    assert ledger.balance(ledger.retirement_account(m)) == D("239.0000")  # 240 / 240 months
    assert retirement.pay_plans(today) == 0  # safe to run twice
    assert retirement.pay_plans(today + timedelta(days=32)) == 1
    assert ledger.balance(ledger.retirement_account(m)) == D("238.0000")  # equal parts of 1
    retirement.stop_plan(m)
    assert retirement.pay_plans(today + timedelta(days=64)) == 0
    assert RetirementPlan.objects.get().active is False


def test_the_payout_page(client):
    from allauth.account.models import EmailAddress

    m = make_member("m@x.org", "M")
    EmailAddress.objects.create(user=m.user, email=m.user.email, verified=True, primary=True)
    client.force_login(m.user)
    assert client.get("/me/retirement/payout/").status_code == 200
