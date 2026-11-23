from decimal import Decimal

import pytest

from apps.tradefund import books, payers, payments
from apps.units.tests.conftest import make_member

from .conftest import make_holder

pytestmark = pytest.mark.django_db
D = Decimal


def pay_all(h, amount):
    """Record a confirmed payment out by a holder, to build up their payment history."""
    recipient = make_member(f"r{h.pk}{amount}@x.org", f"R{h.pk}")
    pr = payments.request_payment(payer=h, amount=amount, currency="EUR", reason_kind="bill", payee_member=recipient)
    payments.confirm_sent(pr, h.member, amount)
    payments.confirm_received(pr, recipient, amount)


def test_one_payer_when_one_can_cover_it():
    a = make_holder("a@x.org", "A", amount=100)
    make_holder("b@x.org", "B", amount=300)
    parts = payers.choose_payers(D("250"), "EUR")
    assert len(parts) == 1 and parts[0][1] == 250
    assert parts[0][0] != a


def test_never_more_than_two():
    for i in range(4):
        make_holder(f"h{i}@x.org", f"H{i}", amount=100)
    assert payers.choose_payers(D("200"), "EUR") and len(payers.choose_payers(D("200"), "EUR")) == 2
    assert payers.choose_payers(D("201"), "EUR") == []  # three would be needed


def test_turns_rotate_across_repeated_requests():
    holders = [make_holder(f"h{i}@x.org", f"H{i}", amount=1000) for i in range(3)]
    used = []
    for _ in range(3):
        ((holder, amount),) = payers.choose_payers(D("100"), "EUR")
        pay_all(holder, amount)
        used.append(holder.pk)
    assert sorted(used) == sorted(h.pk for h in holders)  # everybody paid once


def test_an_excluded_holder_is_never_chosen():
    a = make_holder("a@x.org", "A", amount=500)
    b = make_holder("b@x.org", "B", amount=100)
    parts = payers.choose_payers(D("50"), "EUR", exclude=[a])
    assert [h for h, _ in parts] == [b]


def test_the_reserve_and_open_requests_are_not_available():
    a = make_holder("a@x.org", "A", amount=100)
    books.post_fund(a, "reserve_mark", 60, "reserve", "internal")
    assert payers.choose_payers(D("50"), "EUR") == []
    books.post_fund(a, "reserve_unmark", 60, "release", "internal")
    receiver = make_member("m@x.org", "M")
    payments.request_payment(payer=a, amount=80, currency="EUR", reason_kind="bill", payee_member=receiver)
    assert payers.available(a) == 20


def test_low_trust_holders_are_not_chosen_and_other_currencies_are_separate():
    from apps.tradefund import trust

    a = make_holder("a@x.org", "A", amount=500)
    make_holder("u@x.org", "U", currency="USD", amount=500)
    trust.record(a, "missed")
    assert payers.choose_payers(D("10"), "EUR") == []
    assert len(payers.choose_payers(D("10"), "USD")) == 1
