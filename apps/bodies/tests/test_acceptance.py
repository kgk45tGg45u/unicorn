"""The acceptance check of phase 13 (plan/phase_13_bodies_reputation.md)."""

import pytest
from django.core.management import call_command

from apps.bodies import duties, local, services
from apps.bodies.models import LocalCouncil
from apps.catalogue import services as catalogue
from apps.catalogue.models import Offer
from apps.logistics.models import PickupPoint
from apps.market.models import Order
from apps.market.tests.conftest import World
from apps.members.models import Member
from apps.reputation import services as reputation
from apps.tickets import routing
from apps.tickets import services as ticket_services
from apps.tickets.models import HelpfulMark, Notification, Seat
from apps.tickets.tests.conftest import answer, open_seats, pool, ticket_with_brief
from apps.units import services as unit_services

from .conftest import council_unit, make_member

pytestmark = pytest.mark.django_db


def test_phase_13_acceptance(client):
    call_command("loaddata", "contracts", verbosity=0)

    # 1. Two woodshops form the woodworkers' union through their councils' tickets, and each sends a delegate.
    shop_a, crew_a = council_unit("oak-and-co", ["a0@x.org", "a1@x.org", "a2@x.org"])
    shop_b, crew_b = council_unit("beech-works", ["b0@x.org", "b1@x.org", "b2@x.org"])
    union = services.form_union(crew_a[0], shop_a, "Woodworkers", ["wood"], "People who make things of wood")
    for p in crew_a:  # the founding unit's council decides on its own joining
        unit_services.vote(shop_a.decisions.get(), p, "yes")
    ticket = services.invite_unit(crew_a[0], union, shop_b)
    services.accept_invitation(ticket, crew_b[0])
    for p in crew_b:
        unit_services.vote(shop_b.decisions.get(), p, "yes")
    union.refresh_from_db()
    assert union.status == "active"
    assert {d.member for d in services.current_delegates(union)} == {crew_a[0], crew_b[0]}

    # 2. A question about a chair offer notifies the union's delegates; the answer is marked as advice and the
    #    decision method is unchanged.
    chair = catalogue.create_item("Oak chair", "product", "pc", unit=shop_a, trade_code="wood")
    offer = Offer.objects.create(unit=shop_a, item=chair, status="draft")
    asker = make_member("asker@x.org", "Asker")
    question = ticket_services.create_ticket(
        "question", asker, "Is the oak chair safe for children?", action_payload={"offer_id": offer.pk}
    )
    for delegate in (crew_a[0], crew_b[0]):
        assert Notification.objects.filter(member=delegate, text__contains="asked to advise").exists()
    duties.give_advice(question, crew_b[0], union, "Round the corners and use a safe finish.")
    question.refresh_from_db()
    assert question.decision_method == "none" and duties.advice_comment_ids(question)
    client.force_login(crew_a[0].user)
    assert "(not binding)" in client.get(f"/tickets/{question.number}/").content.decode()

    # 3. A local council for the postcode prefix 10 opens with random confirmers from that area and opens a
    #    pickup point.
    area = pool(14, prefix="area")
    Member.objects.filter(pk__in=[m.pk for m in area]).update(postcode="10115", country="DE")
    for m in area:
        m.refresh_from_db()
    opening = local.propose_council(area[0], "Berlin Mitte", "10", "district")
    assert {s.member_id for s in open_seats(opening)} <= {m.pk for m in area}
    for seat in open_seats(opening):
        answer(seat, "yes")
    council = LocalCouncil.objects.get(postcode_prefix="10")
    point = {"name": "Corner shop", "address": "Main Street 1", "postcode": "10115"}
    pickup = local.propose_decision(
        area[1], council, "A pickup point", "Parcels can wait there.", "open_pickup_point", {"point": point}
    )
    for seat in open_seats(pickup):
        answer(seat, "yes")
    assert PickupPoint.objects.get().managed_by_local_council == council

    # 4. Three helpful marks give a member a reputation, and a new question about wood suggests them.
    wise = crew_b[1]
    old_question = ticket_services.create_ticket(
        "question", asker, "How do I oil oak?", scope="unit", scope_unit=shop_a
    )
    comment = ticket_services.add_comment(old_question, wise, "Use hard wax oil, two thin coats.")
    for i in range(3):
        HelpfulMark.objects.create(comment=comment, member=make_member(f"fan{i}@x.org", f"Fan{i}"))
    reputation.recompute()
    new_question = ticket_services.create_ticket(
        "question", asker, "Which finish for a beech table?", scope="unit", scope_unit=shop_b
    )
    assert routing.suggest_answerers(new_question) == [wise]
    assert Notification.objects.filter(member=wise, text__contains="You might know the answer").exists()

    # 5. A helper with consent places an order for a member without a device. The order shows "on behalf of",
    #    and the helper cannot vote for them.
    world = World()
    helper = make_member("helper@x.org", "Helper")
    helped = world.buyer("helped@x.org", uniq=10)
    from apps.members import assist_services

    consent = assist_services.sign_in_app(assist_services.start(helper, helped, ["orders"]), helped)
    client.force_login(helper.user)
    client.post(f"/assist/{consent.pk}/act/")
    assert client.post(f"/offers/{world.bread.pk}/order/", {"quantity": "1"}).status_code == 302
    order = Order.objects.get()
    assert order.buyer == helped and order.acted_by == helper
    assert "on your behalf" in _orders_page(client, helper, helped, consent)
    voters = pool(8, prefix="v")
    vote_ticket = ticket_with_brief(voters[0])
    seat = Seat.objects.filter(confirmation__ticket=vote_ticket).first()
    second = assist_services.sign_in_app(assist_services.start(helper, seat.member, ["orders"]), seat.member)
    client.post(f"/assist/{second.pk}/act/")
    assert client.post(f"/seat/{seat.pk}/vote/", {"vote": "yes"}).status_code == 403
    seat.refresh_from_db()
    assert seat.vote is None


def _orders_page(client, helper, helped, consent):
    client.force_login(helper.user)
    client.post(f"/assist/{consent.pk}/act/")
    return client.get("/me/orders/").content.decode()
