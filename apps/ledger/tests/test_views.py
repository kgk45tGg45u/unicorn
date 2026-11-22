import csv
import io
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.ledger import services
from apps.ledger.services import Leg, post
from apps.members import services as ms
from apps.members.models import User

pytestmark = pytest.mark.django_db
D = Decimal


def member(email):
    m = ms.create_applicant(User.objects.create_user(email), email, "DE")
    services.open_member_accounts(m)
    return m


def test_a_member_sees_only_their_own_entries(client):
    a, b = member("a@x.org"), member("b@x.org")
    post("hours_pay", "Baking for A", [Leg(services.fund2(), D(-3)), Leg(services.member_account(a), D(3))])
    post("hours_pay", "Cleaning for B", [Leg(services.fund2(), D(-5)), Leg(services.member_account(b), D(5))])
    client.force_login(a.user)
    html = client.get(reverse("ledger:my_uniq")).content.decode()
    assert "Baking for A" in html and "Cleaning for B" not in html
    assert "Paid for hours" in html


def test_running_balance_and_csv_columns(client):
    a = member("a@x.org")
    acc = services.member_account(a)
    post("hours_pay", "pay", [Leg(services.fund2(), D(-4)), Leg(acc, D(4))])
    post("purchase", "bread", [Leg(acc, D(-1)), Leg(services.fund1(), D(1))])
    client.force_login(a.user)
    response = client.get(reverse("ledger:my_uniq_csv"))
    rows = list(csv.reader(io.StringIO(response.content.decode())))
    assert rows[0] == ["date", "kind", "reason", "amount", "balance"]
    assert [r[2:] for r in rows[1:]] == [["bread", "-1.0000", "3.0000"], ["pay", "4.0000", "4.0000"]]


def test_page_needs_login(client):
    assert client.get(reverse("ledger:my_uniq")).status_code == 302


def test_hf08_retirement_balance_is_still_the_members_on_the_page(client):
    a = member("a@x.org")
    post("hours_pay", "pay", [Leg(services.fund2(), D(-4)), Leg(services.member_account(a), D(4))])
    post(
        "retirement_in",
        "save",
        [Leg(services.member_account(a), D(-3)), Leg(services.retirement_account(a), D(3))],
    )
    client.force_login(a.user)
    response = client.get(reverse("ledger:my_uniq"))
    assert response.context["retirement"] == D(3)
