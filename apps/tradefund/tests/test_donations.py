from decimal import Decimal

import pytest

from apps.ledger.models import Transaction
from apps.tradefund import books, donations, fx
from apps.tradefund.models import Donation, FundEntry
from apps.tradefund.tests.test_fx import XML

from .conftest import make_holder

pytestmark = pytest.mark.django_db
D = Decimal


def test_hf18_donation_creates_no_uniq():
    h = make_holder("h@x.org", "H", iban_shown_to_donors=True)
    before = Transaction.objects.count()
    d = donations.pledge("100", "EUR")
    donations.confirm_received(d, h.member)
    assert Transaction.objects.count() == before
    assert not [
        f.name for f in Donation._meta.get_fields() if f.related_model and f.related_model._meta.app_label == "ledger"
    ]
    assert books.holding(h) == D("100.00")
    assert FundEntry.objects.get(kind="donation").reason_kind == "gift"


def test_two_percent_of_a_donation_is_marked_reserve():
    h = make_holder("h@x.org", "H", iban_shown_to_donors=True)
    d = donations.pledge("100", "EUR")
    donations.confirm_received(d, h.member)
    assert books.reserve(h) == D("2.00") and books.free(h) == D("98.00")


def test_usd_donations_go_to_a_usd_holder():
    fx.store_rates(XML)
    eur = make_holder("e@x.org", "E", iban_shown_to_donors=True)
    usd = make_holder("u@x.org", "U", currency="USD", iban_shown_to_donors=True)
    d = donations.pledge("50", "USD", donor_name="Jane Doe")
    assert d.holder == usd and d.holder != eur
    assert b"Jane" not in bytes(d.donor_name_enc) and donations.holder_iban(d).startswith("DE89")
    assert d.reference == f"D-{d.pk:06d}"


def test_only_holders_who_show_their_account_and_have_room_are_chosen():
    make_holder("a@x.org", "A")  # does not show their account
    with pytest.raises(donations.FundError):
        donations.pledge("10", "EUR")
    h = make_holder("b@x.org", "B", iban_shown_to_donors=True)
    with pytest.raises(donations.FundError):
        donations.pledge("301", "EUR")  # more than the base cap of 300
    assert donations.pledge("300", "EUR").holder == h
    with pytest.raises(donations.FundError, match="accepts donations"):
        donations.pledge("10", "GBP")


def test_only_the_receiving_holder_confirms_and_only_once():
    h = make_holder("h@x.org", "H", iban_shown_to_donors=True)
    other = make_holder("o@x.org", "O")
    d = donations.pledge("40", "EUR")
    with pytest.raises(donations.FundError):
        donations.confirm_received(d, other.member)
    donations.confirm_received(d, h.member, "39,50")
    d.refresh_from_db()
    assert d.status == "received" and d.amount == D("39.50")
    with pytest.raises(donations.FundError):
        donations.confirm_received(d, h.member)


def test_a_holder_may_record_a_donation_from_their_own_money():
    h = make_holder("h@x.org", "H")
    d = donations.record_own_donation(h, "20")
    assert d.donor_member == h.member and d.status == "received" and books.holding(h) == D("20.00")


def test_pages(client):
    h = make_holder("h@x.org", "H", iban_shown_to_donors=True)
    assert client.get("/fund/donate/").status_code == 200  # no account needed
    response = client.post("/fund/donate/", {"amount": "25", "currency": "EUR"})
    assert response.status_code == 200 and b"Donations earn no UNIQ" in response.content
    assert b"DE89" in response.content and b"Unicorn donation D-" in response.content
    client.force_login(h.member.user)
    assert client.get("/fund/donations/").status_code == 200
