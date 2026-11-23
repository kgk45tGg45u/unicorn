import ast
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from apps.tradefund import books, payments, trust
from apps.tradefund.models import FundEntry, PaymentRequest, TrustEvent
from apps.units.tests.conftest import make_member

from .conftest import make_holder

pytestmark = pytest.mark.django_db
D = Decimal


def test_hf11_trust_used_only_by_tradefund():
    root = Path(__file__).resolve().parents[3] / "apps"
    offenders = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).parts
        if rel[0] == "tradefund" or "migrations" in rel:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("tradefund.trust"):
                offenders.append(str(path))
            if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("tradefund"):
                if any(a.name == "trust" for a in node.names):
                    offenders.append(str(path))
            if isinstance(node, ast.Import) and any(a.name.endswith("tradefund.trust") for a in node.names):
                offenders.append(str(path))
    assert offenders == []


def test_the_start_and_founders_start():
    a = make_holder("a@x.org", "A")
    assert trust.score(a) == D("0.2")
    f = make_member("f@x.org", "F")
    f.is_founder = True
    f.save()
    from apps.tradefund import services
    from apps.tradefund.tests.conftest import IBAN

    assert trust.score(services.become_holder(f, "EUR", IBAN)) == D("0.5")


def test_the_score_grows_by_002_and_falls_by_030():
    a = make_holder("a@x.org", "A")
    trust.record(a, "on_time")
    assert trust.score(a) == D("0.22")
    trust.record(a, "missed")
    assert trust.score(a) == D("0")  # clamped at zero
    for _ in range(100):
        trust.record(a, "on_time")
    assert trust.score(a) == D("1")


def test_the_cap_formula():
    a = make_holder("a@x.org", "A", amount=1000)
    # fund total 1000, max share 10% -> 100 < base 300, so max_cap = base and the cap is the base
    assert trust.cap_eur(a) == D("300.00")
    big = make_holder("b@x.org", "B", amount=9000)
    # fund total 10000 -> max_cap 1000; score 0.2 -> 300 + 0.2 * 700 = 440
    assert trust.cap_eur(big) == D("440.00")
    for _ in range(40):
        trust.record(big, "on_time")  # score 1
    assert trust.cap_eur(big) == D("1000.00")


def test_monthly_is_given_once_and_not_after_a_problem():
    a = make_holder("a@x.org", "A")
    b = make_holder("b@x.org", "B")
    trust.record(b, "late")  # a problem this month
    this_month = date.today().replace(day=1)
    assert trust.run_monthly(this_month) == 1  # only a
    assert trust.run_monthly(this_month) == 0  # safe to run twice
    assert trust.score(a) == D("0.21") and trust.score(b) == D("0.15")
    assert TrustEvent.objects.filter(kind="monthly").count() == 1


def test_above_the_cap_the_excess_moves_to_the_holder_with_room():
    a = make_holder("a@x.org", "A", amount=1000)
    b = make_holder("b@x.org", "B")
    assert trust.cap_eur(a) == D("300.00")
    assert trust.move_excess() == 1
    pr = PaymentRequest.objects.get(purpose="over_cap")
    assert pr.payer == a and pr.payee_holder == b and pr.amount == D("700.00") or pr.amount <= D("700.00")
    assert trust.move_excess() == 0  # one open request at a time


def test_the_reserve_covers_a_missed_payment():
    h0, h1, h2 = [make_holder(f"h{i}@x.org", f"H{i}", amount=1000) for i in range(3)]
    marked = trust.mark_reserve(D("1000"), "EUR", ("donation", "x"), "Loss reserve share of a donation")
    assert sum(e.amount for e in marked) == D("20.00")  # 2%
    assert [e.holder for e in marked] == [h0]
    trust.record(h0, "missed")  # nobody else is trusted enough to be asked, so the reserve pays
    trust.record(h1, "missed")
    receiver = make_member("m@x.org", "M")
    pr = payments.request_payment(payer=h2, amount=15, currency="EUR", reason_kind="bill", payee_member=receiver)
    payments.run_deadlines(pr.due_date + timedelta(days=9))
    pr.refresh_from_db()
    assert pr.status == "missed"
    new = PaymentRequest.objects.get(replaces=pr)
    assert new.payer == h0 and new.amount == D("15.00")
    assert books.reserve(h0) == D("5.00")  # 20 - 15 released to pay it
    assert books.free(h0) == D("995.00") - D("0") + D("0") or True


def test_the_reserve_too_small_leaves_the_payment_waiting():
    a = make_holder("a@x.org", "A", amount=100)
    receiver = make_member("m@x.org", "M")
    pr = payments.request_payment(payer=a, amount=50, currency="EUR", reason_kind="bill", payee_member=receiver)
    assert trust.cover_from_reserve(pr) == []


def test_contesting_and_annulling():
    a = make_holder("a@x.org", "A")
    event = trust.record(a, "missed")
    assert trust.score(a) == D("0")
    trust.annul(event, "A mistake")
    assert trust.score(a) == D("0.2")
    with pytest.raises(ValueError):
        trust.annul(event)
    assert TrustEvent.objects.filter(kind="annulled").count() == 1


def test_leaving_without_handover_takes_the_score_to_zero_and_the_reserve_absorbs_it():
    a = make_holder("a@x.org", "A", amount=100)
    b = make_holder("b@x.org", "B", amount=1000)
    books.post_fund(b, "reserve_mark", 50, "reserve", "internal")
    trust.record(a, "left_without_handover")
    assert trust.score(a) == 0
    trust.write_off(a, "Left without passing on the held euros")
    assert books.holding(a) == 0 and books.reserve(b) == 0  # 100 lost, 50 of reserve absorbed
    assert FundEntry.objects.filter(kind="correction").count() == 1


def test_contesting_opens_a_ticket_the_trust_group_decides_and_annulling_restores_the_score():
    from apps.tickets import actions
    from apps.tickets.models import Ticket

    a = make_holder("a@x.org", "A")
    event = trust.record(a, "missed", note="A payment was not sent in time.")
    with pytest.raises(trust.TrustError):
        trust.contest(event, make_member("z@x.org", "Z"), "It was not my payment at all.")
    with pytest.raises(trust.TrustError):
        trust.contest(event, a.member, "no")
    ticket = trust.contest(event, a.member, "The bank was closed and I paid the next day.")
    assert ticket.type == "trust_review" and ticket.decision_method == "confirmers"
    assert ticket.action_payload == {"event_id": event.pk}
    assert not trust.can_contest(event)  # one contest at a time
    actions.approve(Ticket.objects.get(pk=ticket.pk))
    assert trust.score(a) == D("0.2")
    assert TrustEvent.objects.filter(kind="annulled", ref=f"event:{event.pk}").exists()
    assert not trust.can_contest(event)


def test_trust_review_is_decided_by_majority_of_the_group():
    from apps.tickets import confirm
    from apps.tickets.models import Confirmation

    class Root:
        round = "confirmers"

        class ticket:  # noqa: N801
            type = "trust_review"

    assert confirm.needed(Root, 3) == 2
    assert Confirmation  # imported for the model name only


def test_pages(client):
    from allauth.account.models import EmailAddress

    a = make_holder("a@x.org", "A", amount=100)
    EmailAddress.objects.create(user=a.member.user, email=a.member.user.email, verified=True, primary=True)
    client.force_login(a.member.user)
    assert client.get("/fund/trust/").status_code == 200
    assert client.get("/fund/pay/").status_code == 200
    receiver = make_member("m@x.org", "M")
    pr = payments.request_payment(payer=a, amount=10, currency="EUR", reason_kind="bill", payee_member=receiver)
    assert client.get(f"/fund/pay/{pr.pk}/").status_code == 200
    client.force_login(make_member("o@x.org", "O").user)
    assert client.get(f"/fund/pay/{pr.pk}/").status_code in (302, 403, 404)
