from decimal import Decimal

import pytest

from apps.core.models import AuditEvent
from apps.ledger import services
from apps.ledger.models import Hold
from apps.ledger.services import LedgerError, Leg, post
from apps.members import services as ms
from apps.members.models import User

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture
def rich():
    m = ms.create_applicant(User.objects.create_user("a@x.org"), "a", "DE")
    services.open_member_accounts(m)
    post("hours_pay", "h", [Leg(services.fund2(), D(-10)), Leg(services.member_account(m), D(10))])
    return m


def test_a_hold_lowers_available_not_balance(rich):
    acc = services.member_account(rich)
    services.place_hold(rich, D(4), "order 1", ("order", 1))
    assert services.balance(acc) == 10 and services.available(acc) == 6


def test_a_held_amount_cannot_be_spent_otherwise(rich):
    acc = services.member_account(rich)
    services.place_hold(rich, D(8), "order 1")
    with pytest.raises(LedgerError, match="Not enough UNIQ"):
        post("purchase", "x", [Leg(acc, D(-3)), Leg(services.fund1(), D(3))])


def test_capturing_posts_a_purchase_and_ends_the_hold(rich):
    acc = services.member_account(rich)
    hold = services.place_hold(rich, D(8), "order 1", ("order", 1))
    tx = services.capture_hold(hold, "delivered")
    hold.refresh_from_db()
    assert hold.status == Hold.CAPTURED and tx.kind == "purchase" and tx.ref_type == "order"
    assert services.balance(acc) == 2 and services.balance(services.fund1()) == 8
    assert services.available(acc) == 2


def test_you_cannot_hold_more_than_available(rich):
    services.place_hold(rich, D(8), "order 1")
    with pytest.raises(LedgerError):
        services.place_hold(rich, D(3), "order 2")


def test_closed_holds_cannot_be_captured_again(rich):
    hold = services.place_hold(rich, D(2), "o")
    services.capture_hold(hold, "done")
    with pytest.raises(LedgerError, match="already closed"):
        services.capture_hold(hold, "again")
    hold2 = services.place_hold(rich, D(2), "o2")
    services.release_hold(hold2, "cancelled")
    with pytest.raises(LedgerError):
        services.capture_hold(hold2, "late")
    assert services.available(services.member_account(rich)) == 8


def test_every_hold_action_is_audited(rich):
    h = services.place_hold(rich, D(2), "o")
    services.release_hold(h, "cancelled")
    assert set(AuditEvent.objects.filter(verb__startswith="hold.").values_list("verb", flat=True)) == {
        "hold.placed",
        "hold.released",
    }
