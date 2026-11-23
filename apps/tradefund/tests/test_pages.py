import csv
import io
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.members import services as ms
from apps.tradefund import books, donations, payments, services, trust
from apps.tradefund.models import FundEntry, Holder, PaymentRequest
from apps.units.tests.conftest import make_member

from .conftest import make_holder, make_ticket

pytestmark = pytest.mark.django_db
D = Decimal


def pay(pr, receiver_member):
    payments.confirm_sent(pr, pr.payer.member, pr.amount)
    payments.confirm_received(pr, receiver_member, pr.amount)


def test_the_public_page_has_no_names_and_no_member_numbers(client):
    a = make_holder("a@x.org", "Alice Secret", amount=200, iban_shown_to_donors=True)
    b = make_holder("b@x.org", "Bob Secret")
    donations.confirm_received(donations.pledge("50", "EUR"), a.member)
    pay(
        payments.request_payment(
            payer=a, amount=40, currency="EUR", reason_kind="internal", payee_holder=b, ticket=make_ticket()
        ),
        b.member,
    )
    response = client.get("/fund/")  # no login needed
    assert response.status_code == 200
    text = response.content.decode()
    for private in ("Alice", "Bob", a.member.number, b.member.number, "x.org"):
        assert private not in text
    assert "€ 250.00" in text and "Donations" in text
    from apps.tradefund import public

    numbers = public.public_numbers()
    assert numbers["holders"] == 2
    assert numbers["in"]["donation"] == D("50.00") and numbers["in"]["setaside"] == D("200.00")
    assert numbers["largest_share"] > 0


def test_euros_out_are_sorted_into_kinds():
    from apps.tradefund import public

    a = make_holder("a@x.org", "A", amount=500)
    entry = books.post_fund(a, "payment_out", -10, "paid", "group_purchase")
    assert public.category_of(entry) == "operations"
    numbers = public.public_numbers()
    assert numbers["out"]["Running costs and other purchases"] == D("10.00")


def test_leaving_is_blocked_while_holding():
    a = make_holder("a@x.org", "A", amount=100)
    assert ms.leave_blockers(a.member)
    assert "still hold 100.00 EUR" in ms.leave_blockers(a.member)[0]
    with pytest.raises(ms.LeaveBlocked):
        ms.leave(a.member)
    with pytest.raises(ms.LeaveBlocked):
        ms.delete_account(a.member)


def test_a_holder_without_a_holding_may_leave():
    a = make_holder("a@x.org", "A")
    assert ms.leave_blockers(a.member) == []
    a.refresh_from_db()
    assert a.status == "left"


def test_handing_over_passes_the_holding_and_the_reserve_to_holders_with_room():
    a = make_holder("a@x.org", "A", amount=200)
    b = make_holder("b@x.org", "B")
    books.post_fund(a, "reserve_mark", 20, "loss reserve", "internal")
    requests = services.hand_over(a)
    assert len(requests) == 1 and requests[0].payee_holder == b and requests[0].amount == D("200.00")
    a.refresh_from_db()
    assert a.status == "leaving" and books.reserve(a) == 0
    assert ms.leave_blockers(a.member)  # still holding until the receiver confirms
    pay(requests[0], b.member)
    a.refresh_from_db()
    assert a.status == "left" and books.holding(a) == 0 and books.holding(b) == D("200.00")
    assert books.reserve(b) == D("20.00")  # the loss reserve moved with the euros
    assert ms.leave_blockers(a.member) == []


def test_a_holder_who_does_not_hand_over_has_vanished_and_the_reserve_covers_it():
    a = make_holder("a@x.org", "A", amount=100)
    b = make_holder("b@x.org", "B", amount=200)
    books.post_fund(b, "reserve_mark", 60, "loss reserve", "internal")
    requests = services.hand_over(a)
    payments.run_deadlines(requests[0].due_date + timedelta(days=9))
    a.refresh_from_db()
    assert a.status == "left" and trust.score(a) == 0
    assert books.holding(a) == 0  # written off
    assert books.reserve(b) == 0  # 60 reserve absorbed 100 of loss as far as it reached
    assert PaymentRequest.objects.get(pk=requests[0].pk).status == "missed"


def test_the_yearly_statement_sums_match_the_fund_entries(client):
    from apps.tradefund import public

    a = make_holder("a@x.org", "A", amount=300)
    b = make_holder("b@x.org", "B")
    ticket = make_ticket()
    pay(
        payments.request_payment(
            payer=a, amount=100, currency="EUR", reason_kind="internal", payee_holder=b, ticket=ticket
        ),
        b.member,
    )
    donations.record_own_donation(a, "25")
    year = timezone.localdate().year
    data = public.statement(a, year)
    entries = FundEntry.objects.filter(holder=a).exclude(kind__in=books.RESERVE_KINDS)
    assert sum(r["amount"] for r in data["rows"]) == sum(e.amount for e in entries) == D("225.00")
    assert data["set_aside"] == D("300.00") and data["sent_on"] == D("100.00") and data["received"] == D("25.00")
    assert data["held_at_year_end"] == books.holding(a)
    assert any(r["ticket"] == ticket.number for r in data["rows"])
    client.force_login(a.member.user)
    assert client.get(f"/fund/statement/{year}/").status_code == 200
    response = client.get(f"/fund/statement/{year}/csv/")
    rows = list(csv.reader(io.StringIO(response.content.decode())))
    assert rows[0][0] == "date" and len(rows) == 1 + len(entries)
    assert client.get("/fund/me/").status_code == 200
    other = make_member("o@x.org", "O")
    client.force_login(other.user)
    assert client.get(f"/fund/statement/{year}/").status_code == 404
    assert not Holder.objects.filter(member=other).exists()
