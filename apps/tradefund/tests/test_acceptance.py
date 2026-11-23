"""The acceptance check of phase 08 (plan/phase_08_trade_fund.md)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.catalogue import services as cat
from apps.market.models import PurchaseNeed
from apps.market.tests.conftest import World
from apps.members import services as ms
from apps.tickets.models import Ticket
from apps.tickets.tests.conftest import answer, open_seats, pool
from apps.tradefund import books, donations, payments, purchases, services, trust
from apps.tradefund.models import FundEntry, GroupTool, PaymentRequest, PurchaseRequest
from apps.units import services as us
from apps.units.tests.conftest import make_member, make_unit

from .conftest import IBAN, make_holder

pytestmark = pytest.mark.django_db
D = Decimal


def founder_holder(email, name, **kw):
    m = make_member(email, name)
    m.is_founder = True
    m.save()
    return services.become_holder(m, "EUR", IBAN, **kw)


def pay(pr, receiver_member):
    payments.confirm_sent(pr, pr.payer.member, pr.amount)
    payments.confirm_received(pr, receiver_member, pr.amount)


def receipt(member):
    upload = SimpleUploadedFile("r.pdf", b"%PDF-1.4 x", "application/pdf")
    return ms.store_private_file(member, upload, "receipt")


def test_phase_08_acceptance():
    world = World()
    # 1. Two founders become holders (the baker is one of them).
    baker = world.baker
    baker.is_founder = True
    baker.save()
    f1 = services.become_holder(baker, "EUR", IBAN)
    f2 = founder_holder("f2@x.org", "Second", iban_shown_to_donors=True)
    assert trust.score(f1) == trust.score(f2) == D("0.5")

    # 2. A donation of 100 euros is recorded, and 2% of it is marked reserve.
    donation = donations.pledge("100", "EUR")
    assert donation.holder == f2
    donations.confirm_received(donation, f2.member)
    assert books.holding(f2) == D("100.00") and books.reserve(f2) == D("2.00")

    # 3. The bakery's salt need becomes a purchase request: approved by itself, reimbursed, closed with a receipt.
    salt = world.bread.inputs.get(source="buy_outside").item
    PurchaseNeed.objects.create(
        unit=world.bakery_unit,
        item=salt,
        month=timezone.localdate().replace(day=1),
        quantity=D(5),
        euro_estimate=D("3.00"),
    )
    assert purchases.purchase_lists() == 1
    salt_purchase = PurchaseRequest.objects.get()
    assert Ticket.objects.get(pk=salt_purchase.ticket_id).decision_method == "auto"
    salt_purchase.refresh_from_db()
    assert salt_purchase.pay_method == "reimburse" and salt_purchase.buyer == f1
    request = PaymentRequest.objects.get(ref_id=str(salt_purchase.pk))
    assert request.payer == f2 and request.payee_holder == f1
    pay(request, baker)
    purchases.record_purchase(salt_purchase, baker, receipt(baker), D("2.80"))
    purchases.mark_delivered(salt_purchase, baker)
    salt_purchase.refresh_from_db()
    assert salt_purchase.status == "closed" and salt_purchase.receipt_id

    # 4. A 300 euro tool purchase is approved by four confirmers and pooled to a buyer from two holders.
    h3 = make_holder("h3@x.org", "Third", amount=250)
    h4 = make_holder("h4@x.org", "Fourth", amount=250)
    buyer = make_holder("buyer@x.org", "Buyer")
    wood = make_member("wood@x.org", "Woodworker")
    unit = make_unit("woodshop")
    us.add_first_worker(unit, wood)
    chair = cat.create_item("Chair", "product", "pc")
    offer = cat.create_offer(
        wood, unit, chair, batch_size=D(4), cycle_days=3, setup_minutes=30, direct_minutes_per_batch=480
    )
    tool = cat.add_tool(wood, offer, "Lathe", "to_buy", D(1), D(1000))
    pool(8)  # members who may be drawn as confirmers
    tool_purchase = purchases.create_purchase(
        wood, "A lathe", D("300.00"), seller="Tool Shop", unit=unit, source="tool", offer_tool=tool, item=tool.tool_item
    )
    ticket = Ticket.objects.get(pk=tool_purchase.ticket_id)
    assert ticket.decision_method == "confirmers"
    for seat in open_seats(ticket):
        answer(seat, "yes")
    ticket.refresh_from_db()
    tool_purchase.refresh_from_db()
    assert ticket.status == "in_action" and tool_purchase.pay_method == "pooled_to_buyer"
    purchases.volunteer(tool_purchase, buyer.member)
    assert purchases.pick_buyer(tool_purchase, timezone.now() + timedelta(days=4)) == buyer
    parts = list(PaymentRequest.objects.filter(ref_id=str(tool_purchase.pk)))
    assert {p.payer for p in parts} == {h3, h4} and sum(p.amount for p in parts) == D("300.00")
    for p in parts:
        pay(p, buyer.member)
    purchases.record_purchase(tool_purchase, buyer.member, receipt(buyer.member), D("295.00"))
    purchases.mark_delivered(tool_purchase, wood)
    assert GroupTool.objects.get().lent_to_unit == unit
    assert cat.publish_offer(offer, wood).status == "active"  # the woodshop's chair offer is unblocked

    # 5. A missed payment lowers the trust score and is covered from the reserve.
    trust.mark_reserve(D("1000"), "EUR", ("setaside", "test"), "Loss reserve share of a set-aside")
    reserve_holder = max((h for h in (f1, f2, h3, h4, buyer)), key=lambda h: books.reserve(h))
    receiver = make_member("m@x.org", "M")
    before = trust.score(h4)
    due = payments.request_payment(payer=h4, amount=15, currency="EUR", reason_kind="bill", payee_member=receiver)
    from apps.tradefund.models import Holder

    Holder.objects.exclude(pk__in=[h4.pk, reserve_holder.pk]).update(status="paused")  # nobody else can pay
    trust.record(reserve_holder, "missed")
    trust.record(reserve_holder, "missed")  # and the reserve's keeper is not asked to pay as an ordinary payer
    payments.run_deadlines(due.due_date + timedelta(days=9))
    assert trust.score(h4) < before
    replacement = PaymentRequest.objects.get(replaces=due)
    assert replacement.payer == reserve_holder and replacement.amount == D("15.00")
    assert FundEntry.objects.filter(kind="reserve_unmark", ref_type="paymentrequest", ref_id=str(due.pk)).exists()
