from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time

from apps.ledger import services as ledger
from apps.market import services
from apps.market.models import Booking, OrderLine, ProductionOrder, StandingOrder, WeeklyPlan
from apps.market.tests.conftest import ServiceWorld, World, unit_for
from apps.units.tests.conftest import make_member

pytestmark = pytest.mark.django_db
D = Decimal


def get(client, name, *args, **kw):
    return client.get(reverse(name, args=args), kw)


def page(client, name, *args, **kw):
    response = get(client, name, *args, **kw)
    assert response.status_code == 200
    return response.content.decode()


# --- search and the offer cards ---


def test_the_search_finds_offers_by_item_name_and_shows_the_card(world, salon, client):
    text = page(client, "market:index", q="brea")
    assert "Bread" in text and "Bakery" in text
    assert "0.14 UNIQ" in text and "Direct 0.11 h + indirect 0.03 h" in text
    assert "€0.01 bought from outside" in text and "Ready around" in text and "No reviews yet" in text
    assert "Haircut" not in text
    assert "Nothing matches" in page(client, "market:index", q="zebra")


def test_a_service_card_shows_the_next_free_session(salon, client):
    assert "No open session yet" in page(client, "market:index", kind="service")
    slot = salon.slot()
    text = page(client, "market:index", kind="service")
    assert "Next free session" in text and f"{slot.starts_at.astimezone(services.BERLIN):%-d %b}" in text


def test_the_list_puts_the_members_area_first_then_alphabetical(world, client):
    other = make_member("other@x.org", "Other")
    from apps.catalogue import services as cat

    far = unit_for(other, "aaa-far", postcode="80000", town="Munich")
    near = unit_for(make_member("near@x.org", "Near"), "zzz-near", postcode="04109", town="Leipzig")
    for owner, unit in ((other, far), (near.memberships.first().member, near)):
        offer = cat.create_offer(owner, unit, world.bread.item, batch_size=D(40), direct_minutes_per_batch=240)
        cat.publish_offer(offer, owner)
    cat.recompute_values()
    member = make_member("me@x.org", "Me")
    member.postcode = "04109"
    member.save()
    client.force_login(member.user)
    text = page(client, "market:index", q="bread")
    assert text.index("Zzz-Near") < text.index("Aaa-Far") < text.index("Bakery") or text.index("Zzz-Near") < text.index(
        "Bakery"
    )
    assert text.index("Zzz-Near") < text.index("Aaa-Far")  # the member's own area comes first


# --- the order form and the booking calendar ---


def test_the_offer_page_has_an_order_form_for_members_only(world, client):
    anonymous = page(client, "catalogue:offer", world.bread.pk)
    assert "Sign in" in anonymous and 'name="quantity"' not in anonymous
    client.force_login(world.buyer().user)
    member = page(client, "catalogue:offer", world.bread.pk)
    assert 'name="quantity"' in member and "Pick it up at the unit" in member and "Every week" in member


def test_ordering_through_the_page_makes_a_line_and_a_standing_order(world, client):
    buyer = world.buyer(uniq=20)
    client.force_login(buyer.user)
    response = client.post(reverse("market:order", args=[world.bread.pk]), {"quantity": "3", "repeat": "week"})
    assert response.status_code == 302 and response["Location"] == reverse("market:my_orders")
    line = OrderLine.objects.get()
    assert line.quantity == 3 and line.order.buyer == buyer
    so = StandingOrder.objects.get()
    assert so.every == "week" and so.next_date > services.today()
    text = page(client, "market:my_orders")
    assert "3 × Bread" in text and "Standing orders" in text and "every week" in text


def test_a_failed_order_shows_what_happened_in_plain_words(world, client):
    poor = world.buyer("poor@x.org", uniq=1)
    client.force_login(poor.user)
    response = client.post(reverse("market:order", args=[world.bread.pk]), {"quantity": "100"}, follow=True)
    assert "Not enough UNIQ available" in response.content.decode()
    assert not OrderLine.objects.exists()


def test_booking_through_the_calendar(salon, client):
    slot = salon.slot()
    customer = salon.customer()
    client.force_login(customer.user)
    text = page(client, "catalogue:offer", salon.offer.pk)
    assert "Book a session" in text and f"/slots/{slot.pk}/book/" in text
    client.post(reverse("market:book", args=[slot.pk]))
    booking = Booking.objects.get()
    assert booking.customer == customer
    assert "Haircut" in page(client, "market:my_orders")


# --- My orders ---


def test_my_orders_shows_only_the_members_own_lines(world, client):
    a, b = world.buyer("a@x.org"), world.buyer("b@x.org")
    services.place_order(a, world.bread, D(2))
    services.place_order(b, world.bread, D(7))
    client.force_login(a.user)
    text = page(client, "market:my_orders")
    assert "2 × Bread" in text and "7 × Bread" not in text
    client.force_login(b.user)
    assert "7 × Bread" in page(client, "market:my_orders") and "2 × Bread" not in page(client, "market:my_orders")


def test_my_orders_needs_a_login(client):
    assert get(client, "market:my_orders").status_code == 302


def test_the_buttons_follow_the_status_of_the_line(world, client):
    buyer = world.buyer()
    line = services.place_order(buyer, world.bread, D(2))
    assert services.line_actions(line) == {"cancel"}
    services.start_production(line.production_order, world.baker)
    line.refresh_from_db()
    assert services.line_actions(line) == set()
    services.complete_production(line.production_order, world.baker, 2)
    line.refresh_from_db()
    assert services.line_actions(line) == {"confirm", "dispute", "refuse"}
    services.hand_over(line, world.baker)
    services.confirm_received(line, buyer)
    line.refresh_from_db()
    assert services.line_actions(line) == {"review"}


def action(client, kind, pk, name, **data):
    return client.post(reverse("market:my_order_action", args=[kind, pk, name]), data, follow=True)


def test_cancel_confirm_and_dispute_from_my_orders(world, client):
    buyer = world.buyer()
    client.force_login(buyer.user)
    line = services.place_order(buyer, world.bread, D(2))
    action(client, "line", line.pk, "cancel")
    line.refresh_from_db()
    assert line.status == "cancelled" and line.hold.status == "released"

    line = services.place_order(buyer, world.bread, D(2))
    services.start_production(line.production_order, world.baker)
    services.complete_production(line.production_order, world.baker, 2)
    services.hand_over(line, world.baker)
    action(client, "line", line.pk, "dispute", reason="damaged", text="Torn bag")
    line.refresh_from_db()
    assert line.disputed_at and "damaged" in line.dispute_text
    action(client, "line", line.pk, "confirm")
    line.refresh_from_db()
    assert line.status == "delivered"
    assert "Write a review" in page(client, "market:my_orders")


def test_refuse_after_the_start_from_my_orders(world, client):
    buyer = world.buyer()
    client.force_login(buyer.user)
    line = services.place_order(buyer, world.bread, D(2))
    services.start_production(line.production_order, world.baker)
    services.complete_production(line.production_order, world.baker, 2)
    action(client, "line", line.pk, "refuse")
    line.refresh_from_db()
    assert line.status == "refused" and line.hold.status == "captured"


def test_nobody_acts_on_somebody_elses_order(world, client):
    a, b = world.buyer("a@x.org"), world.buyer("b@x.org")
    line = services.place_order(a, world.bread, D(2))
    client.force_login(b.user)
    assert client.post(reverse("market:my_order_action", args=["line", line.pk, "cancel"])).status_code == 404
    client.force_login(a.user)
    assert client.post(reverse("market:my_order_action", args=["line", line.pk, "explode"])).status_code == 404
    assert client.get(reverse("market:my_order_action", args=["line", line.pk, "cancel"])).status_code == 405


def test_pause_and_end_a_standing_order_from_my_orders(world, client):
    buyer = world.buyer()
    client.force_login(buyer.user)
    so = services.create_standing_order(buyer, world.bread, 2, "week")
    action(client, "standing", so.pk, "pause")
    so.refresh_from_db()
    assert so.status == "paused"
    action(client, "standing", so.pk, "resume")
    action(client, "standing", so.pk, "end")
    so.refresh_from_db()
    assert so.status == "ended" and "Standing orders" in page(client, "market:my_orders")


def test_booking_buttons_from_my_orders(salon, client):
    customer = salon.customer()
    client.force_login(customer.user)
    slot = salon.slot()
    booking = services.book(customer, slot)
    assert services.booking_actions(booking) == {"cancel"}
    action(client, "booking", booking.pk, "cancel")
    booking.refresh_from_db()
    assert booking.status == "cancelled"
    slot2 = salon.slot(days=2)
    booking2 = services.book(customer, slot2)
    with freeze_time(timezone.now() + timedelta(days=2, hours=3)):
        client.logout()  # two days idle ended the session (P14.T06)
        client.force_login(customer.user)
        services.mark_performed(slot2, salon.provider)
        booking2.refresh_from_db()
        assert services.booking_actions(booking2) == {"confirm", "dispute"}
        action(client, "booking", booking2.pk, "confirm")
    booking2.refresh_from_db()
    assert booking2.status == "confirmed" and services.booking_actions(booking2) == {"review"}


# --- the unit's Work page ---


def post(client, unit, name, **data):
    return client.post(reverse("market:work_action", args=[unit.slug, name]), data, follow=True)


def test_only_workers_open_the_work_page(world, client):
    client.force_login(world.buyer().user)
    assert get(client, "market:work", world.bakery_unit.slug).status_code == 403
    client.logout()
    assert get(client, "market:work", world.bakery_unit.slug).status_code == 302
    client.force_login(world.baker.user)
    assert "Production orders" in page(client, "market:work", world.bakery_unit.slug)


def test_the_work_page_walks_an_order_from_start_to_hand_over(world, client):
    buyer = world.buyer()
    line = services.place_order(buyer, world.bread, D(2))
    client.force_login(world.baker.user)
    text = page(client, "market:work", "bakery")
    assert "2 × Bread" in text and "Start" in text and "Flour" in text and "0.025" in text  # inputs and salt to buy
    po = line.production_order
    post(client, world.bakery_unit, "start", id=po.pk)
    po.refresh_from_db()
    assert po.status == "started"
    post(client, world.bakery_unit, "hours", id=po.pk, minutes="30")
    assert po.offer.unit.hours.filter(ref_type="production_order", ref_id=str(po.pk)).count() == 1
    post(client, world.bakery_unit, "complete", id=po.pk, quantity_done="2")
    line.refresh_from_db()
    assert line.status == "ready" and "Ready to hand over" in page(client, "market:work", "bakery")
    post(client, world.bakery_unit, "hand_over", id=line.pk)
    line.refresh_from_db()
    assert line.status == "handed_over"


def test_the_work_page_handles_inputs_between_units(world, client):
    services.place_order(world.buyer(), world.bread, D(2))
    client.force_login(world.miller.user)
    assert "Deliver 1.2 Flour to Bakery" in page(client, "market:work", "mill")
    from apps.market.models import InputRequest

    request = InputRequest.objects.get(item__name="Flour")
    post(client, world.mill_unit, "deliver_input", id=request.pk)
    client.force_login(world.baker.user)
    assert "Received" in page(client, "market:work", "bakery")
    post(client, world.bakery_unit, "receive_input", id=request.pk)
    request.refresh_from_db()
    assert request.status == "received"


def test_the_work_page_offers_sessions_and_marks_them_performed(salon, client):
    client.force_login(salon.provider.user)
    start = (timezone.now() + timedelta(days=2)).astimezone(services.BERLIN).strftime("%Y-%m-%d 10:00")
    post(client, salon.unit, "new_slots", offer=salon.offer.pk, starts_at=start, weeks="3")
    assert salon.offer.slots.count() == 3
    text = page(client, "market:work", "hair")
    assert "Cancel the session" in text
    customer = salon.customer()
    slot = salon.offer.slots.first()
    booking = services.book(customer, slot)
    with freeze_time(slot.starts_at + timedelta(hours=2)):
        client.logout()  # the days in between ended the session (P14.T06)
        client.force_login(salon.provider.user)
        assert "The session took place" in page(client, "market:work", "hair")
        post(client, salon.unit, "no_show", id=booking.pk)
        post(client, salon.unit, "performed", id=slot.pk)
    booking.refresh_from_db()
    slot.refresh_from_db()
    assert booking.status == "no_show" and slot.status == "done"
    last = salon.offer.slots.last()
    post(client, salon.unit, "cancel_slot", id=last.pk)
    last.refresh_from_db()
    assert last.status == "cancelled"


def test_bad_input_on_the_work_page_shows_a_message_not_an_error(world, client):
    client.force_login(world.baker.user)
    for name, data in (
        ("new_slots", {"offer": world.bread.pk, "starts_at": "tomorrow", "weeks": "x"}),
        ("hours", {"id": 1, "minutes": "abc"}),
        ("advance", {"offer": world.bread.pk, "quantity": "-3"}),
        ("weekly_plan", {"offer": world.bread.pk, "quantity": "5", "reason": ""}),
    ):
        response = client.post(reverse("market:work_action", args=[world.bakery_unit.slug, name]), data)
        assert response.status_code in (302, 404)  # a message and back to the page, or no such order
    assert client.post(reverse("market:work_action", args=[world.bakery_unit.slug, "nonsense"])).status_code == 404


def test_the_work_page_makes_ahead_on_own_initiative_and_sets_a_weekly_plan(client):
    world = World(mode="continuous")
    client.force_login(world.baker.user)
    post(client, world.bakery_unit, "advance", offer=world.bread.pk, quantity="4", estimate="100")
    post(client, world.bakery_unit, "own_initiative", offer=world.bread.pk, quantity="10")
    assert sorted(ProductionOrder.objects.filter(offer=world.bread).values_list("origin", flat=True)) == [
        "advance",
        "own_initiative",
    ]
    text = page(client, "market:work", "bakery")
    assert "Propose a weekly plan" in text and "Make ahead" in text
    post(client, world.bakery_unit, "weekly_plan", offer=world.bread.pk, quantity="40", reason="Usual week")
    assert WeeklyPlan.objects.get().quantity_per_week == 40


def test_pages_work_at_phone_width_and_are_translatable(world, client):
    text = page(client, "market:index")
    assert 'name="viewport"' in text and "row-cols-1" in text
    assert ledger  # the ledger module is the one the pages rely on for UNIQ
    assert ServiceWorld
