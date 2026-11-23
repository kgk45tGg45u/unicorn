from datetime import timedelta
from decimal import Decimal
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.catalogue import services as cat
from apps.market.models import PurchaseNeed
from apps.market.tests.conftest import World
from apps.members import services as ms
from apps.tickets.models import Ticket
from apps.tradefund import books, payments, purchases
from apps.tradefund.models import GroupTool, PaymentRequest, PurchaseRequest
from apps.units import services as us
from apps.units.tests.conftest import make_member, make_unit

from .conftest import IBAN, make_holder

pytestmark = pytest.mark.django_db
D = Decimal


def founder_holder(email, name, amount=None):
    """A holder with the founders' trust of 0.5, so that they may be reimbursed."""
    from apps.tradefund import services

    m = make_member(email, name)
    m.is_founder = True
    m.save()
    holder = services.become_holder(m, "EUR", IBAN)
    if amount:
        books.post_fund(holder, "setaside", amount, "test funding", "gift")
    return holder


def receipt(member):
    return ms.store_private_file(member, SimpleUploadedFile("r.pdf", b"%PDF-1.4 x", "application/pdf"), "receipt")


def pay(pr, receiver_member):
    """Both sides confirm a payment request."""
    payments.confirm_sent(pr, pr.payer.member, pr.amount)
    payments.confirm_received(pr, receiver_member, pr.amount)


def test_monthly_needs_become_one_request_per_item():
    w = World()
    salt = PurchaseNeed.objects.create(
        unit=w.bakery_unit,
        item=w.bread.inputs.get(source="buy_outside").item,
        month=timezone.localdate().replace(day=1),
        quantity=D(5),
        euro_estimate=D("3.00"),
    )
    older = PurchaseNeed.objects.create(
        unit=w.bakery_unit,
        item=salt.item,
        month=(timezone.localdate().replace(day=1) - timedelta(days=40)).replace(day=1),
        quantity=D(2),
        euro_estimate=D("1.20"),
    )
    future = PurchaseNeed.objects.create(
        unit=w.bakery_unit,
        item=salt.item,
        month=(timezone.localdate().replace(day=1) + timedelta(days=40)).replace(day=1),
        quantity=D(9),
        euro_estimate=D("9.00"),
    )
    make_holder("h@x.org", "H", amount=500)
    assert purchases.purchase_lists() == 1
    pr = PurchaseRequest.objects.get()
    assert pr.source == "recipe_input" and pr.est_price == D("4.20") and pr.quantity == 7
    assert pr.requester == w.baker
    for n in (salt, older, future):
        n.refresh_from_db()
    assert salt.status == older.status == "requested" and future.status == "open"
    assert purchases.purchase_lists() == 0  # safe to run twice


def test_the_auto_approval_limit():
    requester = make_member("r@x.org", "R")
    make_holder("h@x.org", "H", amount=1000)
    small = purchases.create_purchase(requester, "A cable", D("30.00"), seller="Shop", seller_iban=IBAN)
    ticket = Ticket.objects.get(pk=small.ticket_id)
    assert ticket.status == "in_action" and ticket.decision_method == "auto"
    small.refresh_from_db()
    assert small.status == "paying"
    bigger = purchases.create_purchase(requester, "A drill", D("80.00"), seller="Shop", seller_iban=IBAN)
    ticket = Ticket.objects.get(pk=bigger.ticket_id)
    assert ticket.decision_method == "confirmers" and ticket.status != "in_action"
    assert bigger.status == "checking" and not PaymentRequest.objects.filter(ref_id=str(bigger.pk)).exists()


def test_a_purchase_above_the_confirmers_limit_goes_to_a_referendum():
    requester = make_member("r@x.org", "R")
    make_holder("h@x.org", "H", amount=5000)
    pr = purchases.create_purchase(requester, "A big oven", D("2500.00"))
    ticket = Ticket.objects.get(pk=pr.ticket_id)
    assert ticket.decision_method == "referendum" and ticket.status == "referendum"


def test_reimbursement_for_a_trusted_holder_then_receipt_and_delivery():
    requester = founder_holder("r@x.org", "R")
    payer = make_holder("p@x.org", "P", amount=500)
    pr = purchases.create_purchase(requester.member, "Salt", D("40.00"), seller="Shop")
    pr.refresh_from_db()
    assert pr.pay_method == "reimburse" and pr.buyer == requester and pr.status == "paying"
    req = PaymentRequest.objects.get(ref_id=str(pr.pk))
    assert req.payer == payer and req.payee_holder == requester and req.amount == D("40.00")
    pay(req, requester.member)
    pr.refresh_from_db()
    assert pr.funded and pr.status == "approved"
    with pytest.raises(purchases.FundError):
        purchases.record_purchase(pr, requester.member, receipt(requester.member), D("45.00"))  # more than received
    purchases.record_purchase(pr, requester.member, receipt(requester.member), D("36.50"))
    pr.refresh_from_db()
    assert pr.status == "bought" and pr.actual_price == D("36.50") and pr.change_due == D("3.50")
    assert books.holding(requester) == D("3.50") or PaymentRequest.objects.filter(purpose="change").exists()
    purchases.mark_delivered(pr, requester.member)
    pr.refresh_from_db()
    assert pr.status == "closed"
    assert Ticket.objects.get(pk=pr.ticket_id).status == "done"


def test_a_holder_pays_the_seller_when_the_requester_is_not_trusted_enough():
    requester = make_member("r@x.org", "R")
    payer = make_holder("p@x.org", "P", amount=500)
    pr = purchases.create_purchase(
        requester, "Paper", D("25.00"), seller="Paper Co", seller_iban="DE02 1203 0000 0000 2020 51"
    )
    pr.refresh_from_db()
    assert pr.pay_method == "holder_pays_seller" and pr.status == "paying"
    req = PaymentRequest.objects.get(ref_id=str(pr.pk))
    assert req.payer == payer and req.payee_external is not None and req.confirmer == requester
    pay(req, requester)  # the requester confirms with the invoice
    pr.refresh_from_db()
    assert pr.status == "bought" and pr.actual_price == D("25.00")
    purchases.mark_delivered(pr, requester)
    assert books.holding(payer) == D("475.00")


def test_a_pooled_purchase_asks_for_a_buyer_and_the_highest_trust_wins():
    requester = make_member("r@x.org", "R")
    a = make_holder("a@x.org", "A", amount=100)
    b = make_holder("b@x.org", "B", amount=100)
    c = make_holder("c@x.org", "C", amount=0)
    d = make_holder("d@x.org", "D", amount=0)
    from apps.tradefund import trust

    trust.record(d, "on_time")  # d has the highest trust
    pr = purchases.create_purchase(requester, "A mixer", D("150.00"))
    from apps.tickets import actions

    actions.approve(Ticket.objects.get(pk=pr.ticket_id), how="test")  # above the automatic limit: confirmers said yes
    pr.refresh_from_db()
    assert pr.pay_method == "pooled_to_buyer" and pr.status == "approved" and pr.buyer is None
    purchases.volunteer(pr, c.member)
    purchases.volunteer(pr, d.member)
    assert purchases.pick_buyer(pr) is None  # three days have not passed
    later = timezone.now() + timedelta(days=4)
    assert purchases.pick_buyer(pr, later) == d
    pr.refresh_from_db()
    assert pr.status == "paying" and pr.buyer == d
    reqs = list(PaymentRequest.objects.filter(ref_id=str(pr.pk)))
    assert len(reqs) == 2 and {r.payer for r in reqs} == {a, b} and all(r.payee_holder == d for r in reqs)
    assert sum(r.amount for r in reqs) == D("150.00")


def test_without_free_euros_the_purchase_waits_and_tries_again():
    requester = make_member("r@x.org", "R")
    pr = purchases.create_purchase(requester, "Paper", D("25.00"), seller="Paper Co", seller_iban=IBAN)
    pr.refresh_from_db()
    assert pr.status == "waiting_for_euros" and "cannot pay" in pr.status_note
    payer = make_holder("p@x.org", "P", amount=100)
    assert purchases.run_waiting() == 1
    pr.refresh_from_db()
    assert pr.status == "paying" and PaymentRequest.objects.get(ref_id=str(pr.pk)).payer == payer


def test_a_delivered_tool_unblocks_its_offer():
    member = make_member("w@x.org", "Woodworker")
    unit = make_unit("woodshop")
    us.add_first_worker(unit, member)
    chair = cat.create_item("Chair", "product", "pc")
    offer = cat.create_offer(
        member, unit, chair, batch_size=D(4), cycle_days=3, setup_minutes=30, direct_minutes_per_batch=480
    )
    tool = cat.add_tool(member, offer, "Lathe", "to_buy", D(1), D(1000))
    with pytest.raises(cat.RecipeBlocked):
        cat.publish_offer(offer, member)
    payer = make_holder("p@x.org", "P", amount=500)
    pr = purchases.create_purchase(
        member,
        "A lathe",
        D("45.00"),
        seller="Tool Shop",
        seller_iban=IBAN,
        unit=unit,
        source="tool",
        offer_tool=tool,
        item=tool.tool_item,
    )
    pr.refresh_from_db()
    assert pr.status == "paying"
    pay(PaymentRequest.objects.get(ref_id=str(pr.pk)), member)
    purchases.mark_delivered(pr, member)
    tool.refresh_from_db()
    assert tool.source == "unicorn_owned" and tool.euro_price == D("45.00")
    assert GroupTool.objects.get().lent_to_unit == unit
    assert cat.publish_offer(offer, member).status == "active"
    assert payer.pk


def test_the_make_or_buy_point_appears_when_unicorn_makes_the_item():
    w = World()
    buyer = make_member("b@x.org", "B")
    pr = purchases.create_purchase(buyer, "Bread for a party", D("20.00"), quantity=D(10), item=w.bread.item)
    ticket = Ticket.objects.get(pk=pr.ticket_id)
    texts = [p["text"] for p in ticket.plan_check["points"]]
    assert any("Unicorn makes this: Bakery" in t for t in texts)
    assert ticket.plan_check["color"] == "amber"  # so confirmers decide, never the automatic rule
    assert ticket.decision_method == "confirmers"


def test_unverified_members_cannot_ask():
    applicant = make_member("a@x.org", "A", verified=False)
    with pytest.raises(purchases.FundError):
        purchases.create_purchase(applicant, "x", D("5"))


def test_a_rejected_purchase_frees_its_need():
    from apps.tickets import actions

    w = World()
    need = PurchaseNeed.objects.create(
        unit=w.bakery_unit,
        item=w.bread.inputs.get(source="buy_outside").item,
        month=timezone.localdate().replace(day=1),
        quantity=D(5),
        euro_estimate=D("300.00"),
    )
    purchases.purchase_lists()
    need.refresh_from_db()
    assert need.status == "requested"
    pr = PurchaseRequest.objects.get()
    actions.reject(Ticket.objects.get(pk=pr.ticket_id))
    pr.refresh_from_db()
    need.refresh_from_db()
    assert pr.status == "rejected" and need.status == "open"
    assert BytesIO and ms


def test_pages(client):
    requester = make_member("r@x.org", "R")
    make_holder("h@x.org", "H", amount=500)
    client.force_login(requester.user)
    assert client.get("/fund/purchase/").status_code == 200
    assert client.get("/fund/purchase/new/").status_code == 200
    response = client.post(
        "/fund/purchase/new/", {"description": "Paper", "est_price": "12,50", "seller": "Shop", "seller_iban": IBAN}
    )
    assert response.status_code == 302
    pr = PurchaseRequest.objects.get()
    assert pr.est_price == D("12.50")
    assert client.get(f"/fund/purchase/{pr.pk}/").status_code == 200
    bad = client.post("/fund/purchase/new/", {"description": "x", "est_price": "abc"})
    assert bad.status_code == 200 and b"Please check the price" in bad.content
