from datetime import date
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.members import services as ms
from apps.tickets import actions
from apps.tickets.models import Seat, Ticket
from apps.tickets.tests.conftest import pool
from apps.tradefund import allocation, benefits, books
from apps.tradefund.models import BenefitBudget, BenefitClaim, BenefitPayout, PaymentRequest

from .conftest import IBAN, make_holder, make_member, set_param

pytestmark = pytest.mark.django_db
D = Decimal
THIS = timezone.localdate().replace(day=1)


def doc(member):
    return ms.store_private_file(
        member, SimpleUploadedFile("rent.pdf", b"%PDF-1.4 x", "application/pdf"), "benefit_document"
    )


def claim(member, rent="400", income="200", approve=True):
    c = benefits.file_claim(
        member,
        [{"kind": "rent", "amount_eur": rent, "payee_name": "Landlord", "payee_iban": IBAN}],
        income,
        documents=[doc(member)],
    )
    if approve:
        actions.approve(Ticket.objects.get(pk=c.ticket_id), how="test")
        c.refresh_from_db()
    return c


def budget(amount):
    return BenefitBudget.objects.create(month=THIS, target_eur=D(amount), budget_eur=D(amount))


def funded_fund(amount=5000, n=4):
    return [make_holder(f"h{i}@x.org", f"H{i}", amount=amount) for i in range(n)]


def test_a_claim_is_a_ticket_with_a_brief_without_the_name():
    member = make_member("m@x.org", "Mary Secret")
    c = claim(member, approve=False)
    ticket = Ticket.objects.get(pk=c.ticket_id)
    assert ticket.type == "benefit_claim" and ticket.decision_method == "confirmers"
    assert "Mary" not in ticket.brief_md and member.number not in ticket.brief_md
    assert "rent: 400.00" in ticket.brief_md and c.burden_score == D("2.0000")
    assert c.status == "confirming"
    actions.approve(ticket, how="test")
    c.refresh_from_db()
    assert c.status == "active" and c.approved_monthly_eur == D("400.00")


def test_only_seated_confirmers_see_the_documents():
    members = pool(8)
    claimant = members[0]
    c = claim(claimant, approve=False)
    pf = c.documents.get()
    seated = Seat.objects.filter(confirmation__ticket=c.ticket, replaced=False).first()
    assert seated is not None
    seated_ids = {s.member_id for s in Seat.objects.filter(confirmation__ticket=c.ticket)}
    outsider = next(m for m in members if m.pk not in seated_ids and m != claimant)
    assert ms.can_view_file(claimant, pf)
    assert ms.can_view_file(seated.member, pf)
    assert not ms.can_view_file(outsider, pf)
    # once the ticket is decided, the seats lose access
    actions.approve(Ticket.objects.get(pk=c.ticket_id), how="test")
    assert not ms.can_view_file(seated.member, pf)


def test_the_guarantee_is_paid_before_benefits():
    funded_fund()
    a, b = make_member("a@x.org", "A"), make_member("b@x.org", "B")
    heavy = claim(a, rent="400", income="100")
    g = benefits.file_guarantee(b, date(2026, 10, 1), "60", "Unicorn delivered less food than I counted on.")
    actions.approve(Ticket.objects.get(pk=g.ticket_id), how="test")
    budget(100)
    result = benefits.run_monthly(THIS)
    assert result["guarantee"] == 1 and result["benefits"] == 0 and result["waiting"] == 1
    g.refresh_from_db()
    assert g.status == "paid"
    assert BenefitPayout.objects.get(kind="benefit", ref_id=heavy.pk).status == "waiting"
    from apps.tickets.models import Notification

    assert Notification.objects.filter(member=a, text__contains="waits this month").count() == 1
    benefits.run_monthly(THIS)  # safe to run twice, and the member is told only once
    assert Notification.objects.filter(member=a, text__contains="waits this month").count() == 1
    assert PaymentRequest.objects.filter(purpose="benefit").count() == 1


def test_the_heaviest_burden_goes_first():
    funded_fund()
    light = claim(make_member("l@x.org", "L"), rent="400", income="2000")
    heavy = claim(make_member("h@x.org", "Hv"), rent="400", income="100")
    assert heavy.burden_score > light.burden_score
    budget(450)
    result = benefits.run_monthly(THIS)
    assert result["benefits"] == 1 and result["waiting"] == 1
    assert BenefitPayout.objects.get(kind="benefit", ref_id=heavy.pk).status == "requested"
    assert BenefitPayout.objects.get(kind="benefit", ref_id=light.pk).status == "waiting"
    req = PaymentRequest.objects.get(purpose="benefit")
    assert req.reason_kind == "bill" and req.payee_external is not None and req.amount == D("400.00")


def test_a_claim_without_a_landlord_is_paid_to_the_member():
    funded_fund()
    m = make_member("m@x.org", "M")
    c = benefits.file_claim(m, [{"kind": "basic_needs", "amount_eur": "50"}], "0")
    actions.approve(Ticket.objects.get(pk=c.ticket_id), how="test")
    budget(500)
    benefits.run_monthly(THIS)
    req = PaymentRequest.objects.get(purpose="benefit")
    assert req.payee_member == m and req.reason_kind == "gift"


def test_the_budget_moves_toward_the_target_by_a_sixth():
    h = make_holder("h@x.org", "H", amount=1200)
    assert h
    row = benefits.budget_for(THIS)
    assert row.target_eur == D("1200.00") and row.budget_eur == D("200.00")  # 0 + (1200 - 0) / 6
    assert benefits.budget_for(THIS) == row  # set once


def test_the_budget_is_cut_while_the_reserve_is_below_its_minimum():
    h = make_holder("h@x.org", "H", amount=1000)
    books.post_fund(h, "payment_out", -600, "materials", "group_purchase")
    assert allocation.reserve_months() == D("0.67")  # 400 free / 600 a month
    from datetime import timedelta

    last_month = (THIS - timedelta(days=1)).replace(day=1)
    BenefitBudget.objects.create(month=last_month, target_eur=D(0), budget_eur=D(100))
    row = benefits.budget_for(THIS)
    assert row.budget_eur == D("95.00") and "reserve" in row.note


def test_the_budget_is_not_raised_while_an_hour_does_not_buy_enough(monkeypatch):
    from apps.macro import services as macro

    make_holder("h@x.org", "H", amount=1200)
    monkeypatch.setattr(macro, "attractiveness", lambda: D("1.00"))
    assert benefits.budget_for(THIS).budget_eur == D("0.00")


def test_a_second_claim_is_refused_and_the_guarantee_can_be_switched_off():
    m = make_member("m@x.org", "M")
    claim(m, approve=False)
    with pytest.raises(benefits.FundError):
        claim(m, approve=False)
    set_param("economy.benefits.guarantee", False)
    with pytest.raises(benefits.FundError):
        benefits.file_guarantee(m, date(2026, 10, 1), "10", "x")
    with pytest.raises(benefits.FundError):
        benefits.file_claim(make_member("u@x.org", "U", verified=False), [{"kind": "rent", "amount_eur": "1"}], "0")


def test_the_benefits_page(client):
    m = make_member("m@x.org", "M")
    client.force_login(m.user)
    assert client.get("/fund/benefits/").status_code == 200
    response = client.post(
        "/fund/benefits/",
        {"kind1": "rent", "amount1": "300", "payee1": "Landlord", "iban1": IBAN, "income": "100"},
    )
    assert response.status_code == 302
    assert BenefitClaim.objects.get(member=m).burden_score == D("3.0000")
    assert b"Help with my basic bills" in client.get("/fund/benefits/").content
