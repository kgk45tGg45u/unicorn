from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core.models import AuditEvent
from apps.tasks import services as task_services
from apps.tasks.models import Mandate
from apps.tradefund import books, payments, trust
from apps.tradefund.models import FundEntry, PaymentRequest, TrustEvent
from apps.units.tests.conftest import make_member

from .conftest import make_holder, make_ticket

pytestmark = pytest.mark.django_db
D = Decimal


def external(buyer):
    return payments.new_external_payee(buyer, "Seller GmbH", "DE02 1203 0000 0000 2020 51")


def test_matching_confirmations_write_the_fund_entries():
    payer = make_holder("p@x.org", "P", amount=500)
    receiver = make_holder("r@x.org", "R")
    ticket = make_ticket(receiver.member)
    pr = payments.request_payment(
        payer=payer, amount=120, currency="EUR", reason_kind="group_purchase", ticket=ticket, payee_holder=receiver
    )
    assert pr.reference == f"Unicorn trade fund, ticket {ticket.number}"
    payments.confirm_sent(pr, payer.member, "120.00")
    pr.refresh_from_db()
    assert pr.status == "sent"
    payments.confirm_received(pr, receiver.member, "120,00")
    pr.refresh_from_db()
    assert pr.status == "confirmed" and pr.final_amount == 120
    assert books.holding(payer) == 380 and books.holding(receiver) == 120
    kinds = list(FundEntry.objects.order_by("seq").values_list("kind", flat=True))
    assert kinds == ["setaside", "transfer_out", "transfer_in"]
    assert trust.score(payer) == D("0.2200")  # start 0.2 + 0.02 on time


def test_the_receiver_may_confirm_first():
    payer = make_holder("p@x.org", "P", amount=100)
    receiver = make_member("m@x.org", "M")
    pr = payments.request_payment(
        payer=payer, amount=40, currency="EUR", reason_kind="bill", payee_member=receiver, ticket=make_ticket()
    )
    payments.confirm_received(pr, receiver, "40")
    pr.refresh_from_db()
    assert pr.status == "received"
    payments.confirm_sent(pr, payer.member, "40")
    pr.refresh_from_db()
    assert pr.status == "confirmed" and books.holding(payer) == 60


def test_only_the_right_people_can_confirm():
    payer = make_holder("p@x.org", "P", amount=100)
    other = make_member("o@x.org", "O")
    buyer = make_member("b@x.org", "B")
    pr = payments.request_payment(
        payer=payer,
        amount=40,
        currency="EUR",
        reason_kind="group_purchase",
        payee_external=external(buyer),
        confirmer=buyer,
        ticket=make_ticket(buyer),
    )
    with pytest.raises(payments.FundError):
        payments.confirm_sent(pr, other, "40")
    with pytest.raises(payments.FundError):
        payments.confirm_received(pr, other, "40")
    payments.confirm_sent(pr, payer.member, "40")
    payments.confirm_received(pr, buyer, "40")
    pr.refresh_from_db()
    assert pr.status == "confirmed" and pr.confirmed_by_buyer == buyer
    assert books.holding(payer) == 60 and FundEntry.objects.filter(kind="payment_out").count() == 1


def test_a_mismatch_opens_a_flag():
    payer = make_holder("p@x.org", "P", amount=500)
    receiver = make_holder("r@x.org", "R")
    pr = payments.request_payment(
        payer=payer, amount=120, currency="EUR", reason_kind="internal", payee_holder=receiver, ticket=make_ticket()
    )
    payments.confirm_sent(pr, payer.member, "120")
    payments.confirm_received(pr, receiver.member, "100")
    pr.refresh_from_db()
    assert pr.status == "mismatch" and pr.flag_ticket
    from apps.tickets.models import Ticket

    flag = Ticket.objects.get(number=pr.flag_ticket)
    assert flag.type == "flag" and "120" in flag.brief_md and "100" in flag.brief_md
    assert books.holding(payer) == 500  # nothing is booked until members decide


def test_a_decided_mismatch_books_the_amount_that_counts_and_rates_the_wrong_side():
    payer = make_holder("p@x.org", "P", amount=500)
    receiver = make_holder("r@x.org", "R")
    pr = payments.request_payment(
        payer=payer, amount=120, currency="EUR", reason_kind="internal", payee_holder=receiver, ticket=make_ticket()
    )
    payments.confirm_sent(pr, payer.member, "120")
    payments.confirm_received(pr, receiver.member, "100")
    from apps.tickets.models import Ticket

    pr.refresh_from_db()
    flag = Ticket.objects.get(number=pr.flag_ticket)
    payments.dispute_decided(flag, upheld=True)  # the receiver (the reporter) was right
    pr.refresh_from_db()
    assert pr.status == "confirmed" and pr.final_amount == 100
    assert books.holding(receiver) == 100
    assert trust.score(payer) == D("0.0200")  # start 0.2, mismatch against the payer -0.20, then "late"/on time +0.02
    assert trust.score(receiver) == D("0.2")


def test_an_overdue_payment_becomes_missed_and_is_reassigned():
    a = make_holder("a@x.org", "A", amount=500)
    b = make_holder("b@x.org", "B", amount=500)
    receiver = make_member("m@x.org", "M")
    pr = payments.request_payment(
        payer=a, amount=100, currency="EUR", reason_kind="bill", payee_member=receiver, ticket=make_ticket()
    )
    today = pr.due_date
    assert payments.run_deadlines(today) == {"overdue": 0, "missed": 0, "reassigned": 0}
    assert payments.run_deadlines(today + timedelta(days=1))["overdue"] == 1
    pr.refresh_from_db()
    assert pr.status == "overdue"
    counts = payments.run_deadlines(today + timedelta(days=8))
    assert counts["missed"] == 1 and counts["reassigned"] == 1
    pr.refresh_from_db()
    assert pr.status == "missed"
    new = PaymentRequest.objects.get(replaces=pr)
    assert new.payer == b and new.amount == 100 and new.status == "requested"
    assert trust.score(a) == D("0")  # 0.2 start - 0.30, never below zero
    payments.run_deadlines(today + timedelta(days=8))  # safe to run twice: the first request is not missed again
    assert TrustEvent.objects.filter(holder=a, kind="missed").count() == 1
    assert PaymentRequest.objects.filter(replaces=pr).count() == 1


def test_a_late_payment_costs_trust():
    a = make_holder("a@x.org", "A", amount=500)
    receiver = make_member("m@x.org", "M")
    pr = payments.request_payment(
        payer=a, amount=100, currency="EUR", reason_kind="bill", payee_member=receiver, ticket=make_ticket()
    )
    payments.run_deadlines(pr.due_date + timedelta(days=2))
    pr.refresh_from_db()
    assert pr.status == "overdue"
    payments.confirm_sent(pr, a.member, "100")
    payments.confirm_received(pr, receiver, "100")
    assert trust.score(a) == D("0.1500")  # 0.2 - 0.05


def test_a_mandate_cannot_overspend():
    payer = make_holder("p@x.org", "P", amount=1000)
    delegate = make_member("d@x.org", "D")
    ticket = make_ticket(delegate)
    mandate = Mandate.objects.create(
        ticket=ticket,
        delegate=delegate,
        scope_md="Buy",
        powers={"spend_limit_eur": 150},
        starts_at=timezone.now(),
        ends_at=timezone.now() + timedelta(days=30),
    )
    payments.request_payment(
        payer=payer, amount=100, currency="EUR", reason_kind="group_purchase", mandate=mandate, payee_member=delegate
    )
    with pytest.raises(payments.FundError, match="mandate"):
        payments.request_payment(
            payer=payer, amount=60, currency="EUR", reason_kind="group_purchase", mandate=mandate, payee_member=delegate
        )
    payments.request_payment(
        payer=payer, amount=50, currency="EUR", reason_kind="group_purchase", mandate=mandate, payee_member=delegate
    )
    assert task_services.PAYMENT_REQUEST_HOOK is payments.mandate_spend
    with pytest.raises(payments.FundError):
        task_services.spend(mandate, 10)  # 150 are already asked for


def test_the_account_number_is_shown_only_to_the_payer():
    payer = make_holder("p@x.org", "P", amount=100)
    buyer = make_member("b@x.org", "B")
    pr = payments.request_payment(
        payer=payer, amount=10, currency="EUR", reason_kind="bill", payee_external=external(buyer), confirmer=buyer
    )
    assert payments.instructions(pr, payer.member)["iban"] == "DE02120300000000202051"
    assert payments.instructions(pr, buyer)["iban"] is None
    assert not AuditEvent.objects.filter(data__has_key="iban").exists()
    from apps.tickets.models import Notification

    assert not Notification.objects.filter(text__contains="DE02").exists()


def test_a_payer_without_enough_free_euros_is_refused():
    payer = make_holder("p@x.org", "P", amount=50)
    receiver = make_member("m@x.org", "M")
    with pytest.raises(payments.FundError):
        payments.request_payment(payer=payer, amount=60, currency="EUR", reason_kind="bill", payee_member=receiver)
