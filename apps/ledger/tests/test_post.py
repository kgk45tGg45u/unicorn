from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from apps.ledger import services
from apps.ledger.models import Account, AccountBalance, Entry, Transaction
from apps.ledger.services import LedgerError, Leg, post
from apps.members import services as member_services
from apps.members.models import User

pytestmark = pytest.mark.django_db
D = Decimal


def member(email="a@x.org"):
    m = member_services.create_applicant(User.objects.create_user(email), email, "DE")
    services.open_member_accounts(m)
    return m


def pay(m, amount):
    acc = services.member_account(m)
    return post("hours_pay", "hours", [Leg(services.fund2(), -D(amount)), Leg(acc, D(amount))])


def test_hf01_only_hours_and_transfers_debit_fund2():
    m = member()
    acc = services.member_account(m)
    with pytest.raises(LedgerError):
        post("purchase", "x", [Leg(services.fund2(), D(-1)), Leg(acc, D(1))])
    with pytest.raises(LedgerError):
        post("tax", "x", [Leg(services.fund2(), D(-1)), Leg(services.fund1(), D(1))])
    pay(m, 1)  # hours_pay works
    post("transfer", "pension", [Leg(services.fund2(), D(-1)), Leg(acc, D(1))])  # transfer works


def test_hf01_member_cannot_be_credited_from_fund1():
    m = member()
    with pytest.raises(LedgerError):
        post("hours_pay", "x", [Leg(services.fund1(), D(-1)), Leg(services.member_account(m), D(1))])


def test_hf05_no_transfer_between_members():
    a, b = member("a@x.org"), member("b@x.org")
    pay(a, 5)
    with pytest.raises(LedgerError, match="never move between members"):
        post("purchase", "x", [Leg(services.member_account(a), D(-1)), Leg(services.member_account(b), D(1))])
    with pytest.raises(LedgerError):
        post(
            "hours_pay",
            "x",
            [
                Leg(services.fund2(), D(-2)),
                Leg(services.member_account(a), D(1)),
                Leg(services.member_account(b), D(1)),
            ],
        )


def test_hf06_fund1_only_debited_by_cancel():
    m = member()
    pay(m, 5)
    post("purchase", "buy", [Leg(services.member_account(m), D(-2)), Leg(services.fund1(), D(2))])
    with pytest.raises(LedgerError):
        post("transfer", "x", [Leg(services.fund1(), D(-1)), Leg(services.member_account(m), D(1))])
    post("cancel", "period close", [Leg(services.fund1(), D(-2)), Leg(services.fund2(), D(2))])
    assert services.balance(services.fund1()) == 0


def test_hf07_reason_required():
    m = member()
    with pytest.raises(LedgerError, match="written reason"):
        post("hours_pay", "   ", [Leg(services.fund2(), D(-1)), Leg(services.member_account(m), D(1))])


def test_hf04_ledger_knows_no_currency():
    for model in (Transaction, Entry, Account):
        names = {f.name for f in model._meta.get_fields()}
        assert not names & {"currency", "euro", "euros", "eur", "price", "iban"}
    assert not any("exchange" in kind or "eur" in kind for kind, _ in Transaction.KINDS)


def test_sum_must_be_zero():
    m = member()
    with pytest.raises(LedgerError, match="add up to zero"):
        post("hours_pay", "x", [Leg(services.fund2(), D(-1)), Leg(services.member_account(m), D(2))])


def test_at_least_two_legs_and_no_zero_leg():
    m = member()
    with pytest.raises(LedgerError):
        post("hours_pay", "x", [Leg(services.member_account(m), D(0)), Leg(services.fund2(), D(0))])


def test_no_overdraft():
    m = member()
    pay(m, 1)
    with pytest.raises(LedgerError, match="Not enough UNIQ"):
        post(
            "purchase",
            "x",
            [
                Leg(services.member_account(m), D(-2)),
                Leg(services.fund1(), D(2)),
            ],
        )
    assert services.balance(services.member_account(m)) == 1


def test_correction_must_negate_original():
    m = member()
    original = pay(m, 3)
    with pytest.raises(LedgerError):
        post("correction", "oops", [Leg(services.fund2(), D(1)), Leg(services.member_account(m), D(-1))], ref=original)
    post(
        "correction", "wrong hours", [Leg(services.fund2(), D(3)), Leg(services.member_account(m), D(-3))], ref=original
    )
    assert services.balance(services.member_account(m)) == 0
    with pytest.raises(LedgerError, match="already been corrected"):
        post("correction", "again", [Leg(services.fund2(), D(3)), Leg(services.member_account(m), D(-3))], ref=original)


def test_hash_chain_links():
    m = member()
    t1 = pay(m, 1)
    t2 = pay(m, 1)
    assert t1.prev_hash == "0" * 64
    assert t2.prev_hash == t1.hash and t2.seq == t1.seq + 1


def test_pay_hours_legs():
    m = member()
    gross, tax = services.pay_hours_legs(m, 90, D("0.2"))
    assert gross[1].amount == D("1.5") and tax[0].amount == D("-0.3")
    post("hours_pay", "h", gross)
    post("tax", "flat tax", tax)
    assert services.balance(services.member_account(m)) == D("1.2")


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.lists(st.tuples(st.sampled_from(["hours", "buy", "transfer", "cancel"]), st.integers(1, 500)), max_size=12))
def test_random_sequences_keep_books_balanced(steps):
    m = member(f"h{Transaction.objects.count()}-{AccountBalance.objects.count()}@x.org")
    acc = services.member_account(m)
    for what, cents in steps:
        x = D(cents) / 100
        try:
            if what == "hours":
                post("hours_pay", "h", [Leg(services.fund2(), -x), Leg(acc, x)])
            elif what == "transfer":
                post("transfer", "t", [Leg(services.fund2(), -x), Leg(acc, x)])
            elif what == "buy":
                post("purchase", "b", [Leg(acc, -x), Leg(services.fund1(), x)])
            else:
                f1 = services.balance(services.fund1())
                if f1 > 0:
                    post("cancel", "c", [Leg(services.fund1(), -f1), Leg(services.fund2(), f1)])
        except LedgerError:
            pass
    total = sum((r.balance for r in AccountBalance.objects.all()), D("0"))
    assert total == 0
    assert services.balance(acc) >= 0
